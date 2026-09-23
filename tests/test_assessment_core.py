"""Provider parity, ruleset changes, privacy and multi-source regression tests."""
import contextlib
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import assess as A
import assessment.logs as L
from assessment.web import render_html
from tests.test_level_assessment import assistant, user
from tests import test_level_assessment as legacy


def record(kind, payload, ts='2026-09-10T10:00:00Z'):
    return {'type': kind, 'timestamp': ts, 'payload': payload}


def message(role, text='PRIVATE_TEXT', ts='2026-09-10T10:00:00Z'):
    return record('response_item', {'type': 'message', 'role': role,
                                   'content': [{'type': 'input_text' if role == 'user' else 'output_text', 'text': text}]}, ts)


def call(name, args=None, cid='call-1', ts='2026-09-10T10:00:00Z', custom=False):
    return record('response_item', {'type': 'custom_tool_call' if custom else 'function_call',
                                   'call_id': cid, 'name': name,
                                   'input' if custom else 'arguments': args if custom else json.dumps(args or {})}, ts)


def tokens(n, cached=0, out=0, ts='2026-09-10T10:00:00Z'):
    usage = {'input_tokens': n, 'cached_input_tokens': cached, 'output_tokens': out}
    return record('event_msg', {'type': 'token_count', 'info': {
        'total_token_usage': usage, 'last_token_usage': usage}}, ts)


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='assessment-core-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, relative, records):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(r) + '\n' for r in records), encoding='utf-8')
        return path

    def codex(self, records, name='a', sidechain=False, archive=False):
        meta = record('session_meta', {'id': name, 'source': {'subagent': {'other': 'worker'}} if sidechain else 'cli'})
        return self.write(f'{"archived_sessions" if archive else "sessions"}/{name}.jsonl', [meta] + records)

    def cli(self, args, *, stdout=True):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            rc = A.main((['--output', '-'] if stdout else []) + args)
        return rc, out.getvalue(), err.getvalue()


class TestCodex(TempCase):
    def test_response_items_count_once_despite_mirror_events(self):
        self.codex([message('user'), record('event_msg', {'type': 'user_message', 'message': 'PRIVATE_TEXT'}),
                    message('assistant'), record('event_msg', {'type': 'agent_message', 'message': 'PRIVATE_TEXT'}),
                    call('exec_command', {'cmd': 'pytest'}),
                    record('event_msg', {'type': 'exec_command_begin', 'call_id': 'call-1'}),
                    record('event_msg', {'type': 'item_completed', 'item': {'type': 'tool_call'}})])
        m = L.scan_codex(self.root)
        self.assertEqual((m.humanish_user, m.assistant, m.tool_calls), (1, 1, 1))
        self.assertEqual(m.bash['test'], 1)

    def test_response_user_fallback_excludes_injected_context(self):
        self.codex([message('user', '# AGENTS.md instructions for /tmp'),
                    message('user', '<environment_context>data</environment_context>'),
                    message('user', '<turn_aborted>'), message('user', 'implement'),
                    message('developer'), message('assistant')])
        self.assertEqual(L.scan_codex(self.root).humanish_user, 1)

    def test_image_only_human(self):
        self.codex([record('response_item', {'type': 'message', 'role': 'user',
                                            'content': [{'type': 'input_image', 'image_url': 'PRIVATE_IMAGE'}]})])
        self.assertEqual(L.scan_codex(self.root).humanish_user, 1)

    def test_subagent_prompts_not_human(self):
        self.codex([message('user'), message('assistant'), call('apply_patch', 'PRIVATE_PATCH', custom=True)], sidechain=True)
        m = L.scan_codex(self.root)
        self.assertEqual((m.humanish_user, m.subagent_files, m.tool_calls_sidechain), (0, 1, 1))
        self.assertEqual(m.edit_calls, 1)

    def test_patch_then_verification_in_same_thread(self):
        self.codex([call('functions.apply_patch', 'PRIVATE_PATCH', custom=True),
                    call('functions.exec_command', {'cmd': 'uv run pytest'}, cid='call-2')])
        m = L.scan_codex(self.root)
        self.assertEqual((m.edit_calls, len(m.engineering_sessions)), (1, 1))

    def test_unrelated_sessions_do_not_form_workflow(self):
        self.codex([call('apply_patch', 'patch', custom=True)], name='edit')
        self.codex([call('exec_command', {'cmd': 'pytest'}, cid='test')], name='verify')
        self.assertEqual(len(L.scan_codex(self.root).engineering_sessions), 0)

    def test_verification_before_edit_does_not_form_workflow(self):
        self.codex([call('exec_command', {'cmd': 'pytest'}), call('apply_patch', 'patch', cid='patch', custom=True)])
        self.assertEqual(len(L.scan_codex(self.root).engineering_sessions), 0)

    def test_cumulative_tokens_not_summed_or_mirrored(self):
        self.codex([tokens(100, 80, 10), tokens(100, 80, 10), tokens(140, 110, 20)])
        m = L.scan_codex(self.root)
        self.assertEqual((m.input_tokens, m.cache_read, m.output_tokens), (140, 110, 20))

    def test_token_window_uses_baseline_before_since(self):
        self.codex([tokens(100, 80, 10, '2026-09-09T10:00:00Z'), tokens(140, 110, 20)])
        m = L.scan_codex(self.root, since=L.parse_date('2026-09-10'))
        self.assertEqual((m.input_tokens, m.cache_read, m.output_tokens), (40, 30, 10))

    def test_per_response_usage_takes_precedence_and_deduplicates(self):
        usage = record('token_usage_record', {'response_id': 'r1', 'usage': {
            'input_tokens': 70, 'cached_input_tokens': 20, 'output_tokens': 5,
            'reasoning_output_tokens': 3}, 'thread_token_usage': {'input_tokens': 700}})
        self.codex([tokens(70, 20, 5), usage, usage])
        m = L.scan_codex(self.root)
        self.assertEqual((m.input_tokens, m.output_tokens), (70, 5))

    def test_archive_duplicate_not_counted(self):
        path = self.codex([message('user'), call('exec_command', {'cmd': 'pytest'}), tokens(100)])
        archive = self.root / 'archived_sessions'
        archive.mkdir()
        shutil.copy(path, archive / 'copy.jsonl')
        m = L.scan_codex(self.root)
        self.assertEqual((m.humanish_user, m.tool_calls, m.input_tokens, len(m.sessions)), (1, 1, 100, 1))

    def test_archived_only_session_included(self):
        self.codex([message('user')], archive=True)
        self.assertEqual(L.scan_codex(self.root).humanish_user, 1)

    def test_duplicate_call_ids_count_once(self):
        self.codex([call('exec_command', {'cmd': 'pytest'}),
                    call('exec_command', {'cmd': 'pytest'}, ts='2026-09-10T11:00:00Z')])
        self.assertEqual(L.scan_codex(self.root).tool_calls, 1)

    def test_opaque_code_mode_is_disclosed(self):
        self.codex([call('exec', 'const cmd = "PRIVATE_TEXT"; tools.exec_command({cmd});', custom=True)])
        m = L.scan_codex(self.root)
        self.assertEqual(m.tool_calls, 1)
        self.assertEqual(m.bash_total, 0)
        self.assertEqual(m.diagnostics['opaque_orchestrator_calls'], 1)


class TestRulesAndMerge(TempCase):
    def test_large_read_only_trace_not_agent_engineering(self):
        m = L.Metrics()
        m.tool_calls, m.assistant, m.humanish_user = 1000, 200, 10
        m.tools['Task'] = 100
        self.assertEqual(A.evaluate(m, A.load_config(None))['current'], 1)

    def test_no_data_unknown(self):
        self.assertIsNone(A.evaluate(L.Metrics(), {})['current'])

    def test_strings_and_negative_values_cannot_promote(self):
        root = legacy.TestLevels._l4()
        self.addCleanup(shutil.rmtree, root)
        m = L.scan(root)
        flags = A.L5_FLAGS + A.L6_FLAGS + A.L7_FLAGS
        cfg = {k: 'false' for k, _ in flags}
        cfg[A.L5_NUMERIC[0]] = 0.5
        self.assertEqual(A.evaluate(m, cfg)['current'], 4)
        cfg = {k: True for k, _ in flags}
        for value in [-1, float('-inf'), float('inf'), float('nan'), True, '0.5']:
            with self.subTest(value=value):
                cfg[A.L5_NUMERIC[0]] = value
                self.assertEqual(A.evaluate(m, cfg)['current'], 4)

    def test_self_reported_not_verified(self):
        root = legacy.TestLevels._l4()
        self.addCleanup(shutil.rmtree, root)
        cfg = {k: True for k, _ in A.L5_FLAGS + A.L6_FLAGS + A.L7_FLAGS}
        cfg[A.L5_NUMERIC[0]] = 0
        result = A.evaluate(L.scan(root), cfg)
        self.assertEqual((result['current'], result['observed_level'], result['basis']), (7, 4, 'self-reported'))
        self.assertEqual(result['status'][7], 'DECLARED')

    def test_merge_weights_ratios_and_unions_days(self):
        a, b = L.Metrics('claude'), L.Metrics('codex')
        a.humanish_user, a.tool_calls = 2, 20
        b.humanish_user, b.tool_calls = 8, 8
        day = L.parse_date('2026-09-10').date()
        a.days.add(day); b.days.add(day)
        a.sessions.add(('claude', 'same')); b.sessions.add(('codex', 'same'))
        merged = L.merge_metrics([a, b])
        self.assertEqual(merged.tool_per_human, 2.8)
        self.assertEqual((len(merged.days), len(merged.sessions)), (1, 2))

    def test_combining_does_not_join_edit_and_test(self):
        a, b = L.Metrics('claude'), L.Metrics('codex')
        a.edit_calls = 1
        b.bash['test'] = 10
        self.assertEqual(len(L.merge_metrics([a, b]).engineering_sessions), 0)

    def test_config_scopes_are_isolated(self):
        p = self.root / 'config.json'
        p.write_text(json.dumps({'l5': {'autonomous_pr': True}, 'sources': {
            'claude': {'l5': {'autonomous_pr': False}}, 'codex': {'l5': {'autonomous_pr': True}}}}))
        self.assertTrue(A.load_config(p, scope='combined')['autonomous_pr'])
        self.assertFalse(A.load_config(p, scope='claude', allow_legacy=True)['autonomous_pr'])
        self.assertTrue(A.load_config(p, scope='codex')['autonomous_pr'])

    def test_legacy_config_not_applied_to_both_sources(self):
        p = self.root / 'config.json'
        p.write_text(json.dumps({'l5': {'autonomous_pr': True}}))
        self.assertFalse(A.load_config(p, scope='claude')['autonomous_pr'])
        self.assertTrue(A.load_config(p, scope='claude', allow_legacy=True)['autonomous_pr'])


class TestRobustness(TempCase):
    def test_bad_usage_and_cache_do_not_crash(self):
        rec = assistant()
        rec['message']['usage']['input_tokens'] = 'unknown'
        self.write('projects/a.jsonl', [rec, assistant(ts='2026-09-10T10:00:00')])
        (self.root / 'stats-cache.json').write_text('[]')
        m = L.scan(self.root, since=L.parse_date('2026-09-01'))
        self.assertEqual(m.assistant, 2)
        self.assertEqual(m.diagnostics['invalid_numeric_fields'], 1)
        self.assertEqual(m.diagnostics['invalid_stats_cache'], 1)

    def test_timezone_dates_are_normalized_to_utc(self):
        self.write('projects/a.jsonl', [assistant(ts='2026-09-11T01:00:00+08:00')])
        m = L.scan(self.root, until=L.parse_date('2026-09-11'))
        self.assertEqual(m.assistant, 1)
        self.assertEqual(m.first_ts.date().isoformat(), '2026-09-10')

    def test_symlink_transcript_not_read(self):
        target = self.write('outside.jsonl', [assistant()])
        (self.root / 'projects').mkdir()
        (self.root / 'projects' / 'secret.jsonl').symlink_to(target)
        m = L.scan(self.root)
        self.assertEqual(m.records, 0)
        self.assertEqual(m.diagnostics['skipped_symlinks'], 1)

    def test_mixed_human_blocks_order_independent(self):
        blocks = [{'type': 'tool_result'}, {'type': 'image'}]
        for content in [blocks, list(reversed(blocks)), [{'type': 'tool_result'}, {'type': 'text', 'text': 'continue'}]]:
            rec = user('')
            rec['message']['content'] = content
            self.assertTrue(L.is_human_input(rec))

    def test_shell_quote_heredoc_and_wrapper_regressions(self):
        for command, expected in [('echo "hello; pytest"', 'read'),
                                  ('echo ";" pytest', 'read'),
                                  ('echo \"|\" pytest', 'read'),
                                  ('echo ok # ignored; pytest', 'read'),
                                  ('FOO="a b" pytest', 'test'),
                                  ('rg github-actions README.md', 'search'),
                                  ('cat <<EOF > out\npytest\nEOF', 'read'),
                                  ('uv run pytest -q', 'test'),
                                  ('bash -lc "pytest -q"', 'test')]:
            with self.subTest(command=command):
                self.assertEqual(L.classify_bash(command), expected)

    def test_git_pr_ci_are_not_test_verification(self):
        self.write('projects/a.jsonl', [assistant(tools=[('Bash', {'command': 'git status'}),
                                                         ('Bash', {'command': 'gh pr list'})])])
        self.assertEqual(L.scan(self.root).verification_ratio, 0)

    def test_date_validation_and_one_day_includes_only_today(self):
        self.write('projects/a.jsonl', [assistant(ts='2026-09-09T23:59:59Z'), assistant(ts='2026-09-10T00:00:00Z')])
        base = ['--source', 'claude', '--claude-dir', str(self.root), '--no-auto-config']
        for args in [['--days', '0'], ['--days', '-1'], ['--days', '0', '--since', '2026-09-01'],
                     ['--since', '2026-09-20', '--until', '2026-09-01']]:
            self.assertEqual(self.cli(base + args)[0], 2)
        with patch.object(A, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
            rc, output, _ = self.cli(base + ['--days', '1', '--format', 'json'])
        self.assertEqual(rc, 0)
        report = json.loads(output)['reports']['claude']
        self.assertEqual(report['observed']['assistant'], 1)
        self.assertEqual(report['requested_window']['until'], '2026-09-10')


class TestReports(TempCase):
    def fixture(self):
        self.write('claude/projects/a.jsonl', [user('PRIVATE_PROMPT'), assistant(tools=[('Bash', {'command': 'echo PRIVATE_COMMAND'})])])
        self.codex([message('user', 'PRIVATE_PROMPT'), call('apply_patch', 'PRIVATE_PATCH', custom=True)])
        return ['--claude-dir', str(self.root / 'claude'), '--codex-dir', str(self.root), '--no-auto-config']

    def test_source_and_view_matrix(self):
        args = self.fixture()
        for source, view, expected in [('all', 'both', {'combined', 'claude', 'codex'}),
                                       ('all', 'separate', {'claude', 'codex'}),
                                       ('all', 'combined', {'combined'}),
                                       ('claude', 'both', {'claude'}), ('codex', 'combined', {'codex'})]:
            with self.subTest(source=source, view=view):
                rc, output, _ = self.cli(args + ['--source', source, '--view', view, '--format', 'json'])
                self.assertEqual(rc, 0)
                bundle = json.loads(output)
                self.assertEqual(set(bundle['reports']), expected)
                self.assertEqual(bundle['evaluation_methods'],
                                 ['level_assessment_l0_l7', 'anthropic_evals',
                                  'self_improvement_comparison'])

    def test_html_offline_tabs_and_privacy(self):
        args = self.fixture()
        rc, html, _ = self.cli(args + ['--format', 'html'])
        self.assertEqual(rc, 0)
        self.assertIn('id="panel-combined"', html)
        self.assertIn('id="panel-claude"', html)
        self.assertIn('id="panel-codex"', html)
        for secret in ('PRIVATE_PROMPT', 'PRIVATE_COMMAND', 'PRIVATE_PATCH'):
            self.assertNotIn(secret, html)
        self.assertNotIn('src="http', html)
        self.assertNotIn('fetch(', html)
        self.assertIn('role="tab"', html)

    def test_html_defaults_to_english_and_keeps_chinese_choice(self):
        rc, html, _ = self.cli(self.fixture() + ['--format', 'html'])
        self.assertEqual(rc, 0)
        self.assertIn('<html lang="en">', html)
        self.assertIn('data-language-panel="en">', html)
        self.assertIn('data-language-panel="zh" hidden>', html)
        english = html.split('data-language-panel="en">', 1)[1].split('</main>', 1)[0]
        chinese = html.split('data-language-panel="zh" hidden>', 1)[1].split('</main>', 1)[0]
        self.assertIn('Selected period:', english)
        self.assertIn('Evaluation trial coverage:', english)
        self.assertNotIn('统计时间段：', english)
        self.assertNotRegex(english, r'[\u4e00-\u9fff]')
        self.assertIn('统计时间段：', chinese)
        self.assertIn('评测试验覆盖：', chinese)
        self.assertIn("localStorage.getItem(languageKey)", html)
        self.assertIn("localStorage.setItem(languageKey, language)", html)
        ids = re.findall(r'\bid="([^"]+)"', html)
        self.assertEqual(len(ids), len(set(ids)))

    def test_html_escapes_dynamic_content(self):
        m = L.Metrics()
        result = A.evaluate(m, {})
        report = json.loads(A.render_json(m, result, None, None, None))
        report['note'] = '<script>alert("x")</script>'
        html = render_html({'reports': {'claude': report}, 'ruleset_version': '2.0', 'merge_note': 'test'})
        self.assertNotIn('<script>alert', html)
        self.assertIn('&lt;script&gt;', html)

    def test_output_file_and_no_stdout(self):
        args = self.fixture()
        path = self.root / 'nested' / 'reports' / 'report.html'
        rc, output, _ = self.cli(args + ['--format', 'html', '--output', str(path)])
        self.assertEqual((rc, output), (0, ''))
        self.assertTrue(path.read_text().startswith('<!doctype html>'))

    def test_default_reports_use_local_date_and_format_extension(self):
        args = self.fixture()
        previous_cwd = Path.cwd()
        self.addCleanup(os.chdir, previous_cwd)
        os.chdir(self.root)
        with patch.object(A, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 9, 21, 0, 30)
            for fmt, extension in [('text', 'txt'), ('txt', 'txt'), ('md', 'md'),
                                   ('json', 'json'), ('html', 'html')]:
                with self.subTest(format=fmt):
                    rc, output, err = self.cli(args + ['--format', fmt], stdout=False)
                    self.assertEqual((rc, output), (0, ''))
                    path = Path('reports/2026-09-21') / f'ai-engineering-assessment.{extension}'
                    self.assertTrue(path.is_file())
                    self.assertIn(str(path), err)
                    report = path.read_text(encoding='utf-8')
                    self.assertTrue(report.strip())
                    if fmt == 'json':
                        self.assertEqual(set(json.loads(report)['reports']),
                                         {'combined', 'claude', 'codex'})
                    elif fmt == 'html':
                        self.assertTrue(report.startswith('<!doctype html>'))
            path.write_text('stale report', encoding='utf-8')
            self.assertEqual(self.cli(args + ['--format', 'html'], stdout=False)[0], 0)
            self.assertNotIn('stale report', path.read_text(encoding='utf-8'))
        self.assertFalse(list(Path('.').glob('ai-engineering-assessment.*')))

    def test_default_and_explicit_dual_format(self):
        args = self.fixture()
        previous_cwd = Path.cwd()
        self.addCleanup(os.chdir, previous_cwd)
        os.chdir(self.root)
        with patch.object(A, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 9, 21, 0, 30)
            for extra, base in [([], Path('reports/2026-09-21/ai-engineering-assessment')),
                                (['--format', 'txt+html', '-o', 'custom/result.json'],
                                 Path('custom/result'))]:
                with self.subTest(args=extra):
                    rc, output, err = self.cli(args + extra, stdout=False)
                    self.assertEqual((rc, output), (0, ''))
                    txt, html = base.with_suffix('.txt'), base.with_suffix('.html')
                    self.assertIn('Current Level', txt.read_text())
                    self.assertTrue(html.read_text().startswith('<!doctype html>'))
                    self.assertIn(str(txt), err)
                    self.assertIn(str(html), err)
            self.assertFalse(Path('custom/result.json').exists())

    def test_report_name_sets_title_and_default_filename(self):
        args = self.fixture()
        previous_cwd = Path.cwd()
        self.addCleanup(os.chdir, previous_cwd)
        os.chdir(self.root)
        with patch.object(A, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 9, 21, 0, 30)
            rc, output, _ = self.cli(args + ['--report-name', 'Team & Project Review'], stdout=False)
        self.assertEqual((rc, output), (0, ''))
        base = Path('reports/2026-09-21/team-project-review')
        self.assertTrue(base.with_suffix('.txt').read_text().startswith('Team & Project Review'))
        html = base.with_suffix('.html').read_text()
        self.assertIn('<h1>Team &amp; Project Review</h1>', html)
        self.assertIn('download="team-project-review.json"', html)

    def test_report_name_json_and_validation(self):
        args = self.fixture()
        rc, output, _ = self.cli(args + ['--name', 'Custom Assessment', '--format', 'json'])
        self.assertEqual(rc, 0)
        bundle = json.loads(output)
        self.assertEqual(bundle['report_name'], 'Custom Assessment')
        self.assertEqual(bundle['reports']['combined']['report_name'], 'Custom Assessment')
        self.assertEqual(self.cli(args + ['--report-name', '...', '--format', 'json'])[0], 2)

    def test_output_path_overrides_filename_but_keeps_report_name(self):
        args = self.fixture()
        path = self.root / 'my-report.html'
        rc, output, _ = self.cli(args + ['--report-name', 'Team Review',
                                        '--format', 'html', '-o', str(path)])
        self.assertEqual((rc, output), (0, ''))
        html = path.read_text()
        self.assertIn('<h1>Team Review</h1>', html)
        self.assertIn('download="my-report.json"', html)

    def test_dual_format_stdout_requires_single_format(self):
        rc, output, err = self.cli(self.fixture())
        self.assertEqual((rc, output), (2, ''))
        self.assertIn('single --format', err)
        self.assertFalse((self.root / '-').exists())

    def test_html_requested_range_and_actual_coverage(self):
        self.write('claude/projects/a.jsonl', [user('hi', ts='2026-09-10T10:00:00Z')])
        self.codex([message('user', ts='2026-09-12T10:00:00Z')])
        args = ['--claude-dir', str(self.root / 'claude'), '--codex-dir', str(self.root),
                '--no-auto-config', '--format', 'html']
        cases = [([], '全部日志（未限制日期）', True),
                 (['--since', '2026-09-01', '--until', '2026-09-20'],
                  '2026-09-01 至 2026-09-20', True),
                 (['--since', '2026-09-01'], '2026-09-01 至 不限', True),
                 (['--until', '2026-09-20'], '不限 至 2026-09-20', True),
                 (['--since', '2026-10-01'], '2026-10-01 至 不限', False)]
        for extra, requested, has_data in cases:
            with self.subTest(args=extra):
                rc, html, _ = self.cli(args + extra)
                self.assertEqual(rc, 0)
                self.assertEqual(html.count('统计时间段：' + requested), 3)
                if has_data:
                    for coverage in ('2026-09-10 至 2026-09-12',
                                     '2026-09-10 至 2026-09-10',
                                     '2026-09-12 至 2026-09-12'):
                        self.assertIn('实际日志覆盖：' + coverage + ' · UTC', html)
                else:
                    self.assertEqual(html.count('实际日志覆盖：无有效时间记录'), 3)

    def test_output_parent_is_file_exits_2(self):
        args = self.fixture()
        parent = self.root / 'blocked'
        parent.write_text('existing file', encoding='utf-8')
        rc, output, err = self.cli(args + ['--output', str(parent / 'report.txt')])
        self.assertEqual((rc, output), (2, ''))
        self.assertIn('cannot write report', err)
        self.assertEqual(parent.read_text(encoding='utf-8'), 'existing file')

    def test_missing_one_default_source_does_not_mask_existing(self):
        self.codex([message('user')])
        rc, output, _ = self.cli(['--source', 'all', '--claude-dir', str(self.root / 'missing'),
                                  '--codex-dir', str(self.root), '--format', 'json', '--no-auto-config'])
        self.assertEqual(rc, 0)
        self.assertEqual(set(json.loads(output)['reports']), {'combined', 'codex'})


if __name__ == '__main__':
    unittest.main()
