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
                    message('user', '<turn_aborted>'), message('user', '<recommended_plugins>\nPRIVATE_LIST'),
                    message('user', 'implement'),
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
        report = A.build_report(m, A.evaluate(m), None, None)
        self.assertEqual(report['level_visibility']['status'], 'direct')

    def test_venv_python_verification_counts_for_both_sources(self):
        command = '/repo/.venv/bin/python -m unittest discover -s tests'
        self.codex([call('apply_patch', 'patch', custom=True),
                    call('exec_command', {'cmd': command}, cid='verify')])
        self.write('projects/a.jsonl', [assistant(tools=[('Edit', {'file_path': 'a.py'})]),
                                       assistant(tools=[('Bash', {'command': command})])])
        for metrics in (L.scan_codex(self.root), L.scan(self.root)):
            with self.subTest(source=metrics.source):
                self.assertEqual(metrics.verification_calls, 1)
                self.assertEqual(len(metrics.engineering_sessions), 1)
                self.assertEqual(metrics.history.summary()['verification_calls'], 1)

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
        self.codex([call('exec', 'await tools.apply_patch("PRIVATE_PATCH"); '
                         'await tools.exec_command({cmd: "pytest"});', custom=True),
                    record('response_item', {'type': 'custom_tool_call_output',
                                             'call_id': 'call-1', 'output': [
                                                 {'type': 'input_text', 'text': 'Script completed'}]})])
        m = L.scan_codex(self.root)
        self.assertEqual(m.tool_calls, 1)
        self.assertEqual(m.bash_total, 0)
        self.assertEqual((m.edit_calls, len(m.engineering_sessions)), (0, 0))
        self.assertEqual(m.diagnostics['opaque_orchestrator_calls'], 1)
        report = A.build_report(m, A.evaluate(m), None, None)
        self.assertEqual(report['current_level'], 1)
        self.assertEqual(report['level_visibility'], {
            'status': 'partial', 'opaque_orchestrator_calls': 1,
            'may_undercount_edits_and_verification': True})
        html = render_html({'reports': {'codex': report}, 'ruleset_version': '1.0', 'merge_note': 'test'})
        self.assertIn('This level reflects visible logs only', html)


class TestVerificationCoverage(TempCase):
    def output(self, cid, code=0):
        return record('response_item', {'type': 'function_call_output',
                                       'call_id': cid, 'output': {'exit_code': code}})

    def test_final_edit_invalidates_earlier_success_but_retains_level_signal(self):
        self.codex([call('apply_patch', 'patch', 'edit-one', custom=True),
                    call('exec_command', {'cmd': 'pytest'}, 'verify'), self.output('verify'),
                    call('apply_patch', 'patch', 'edit-two', custom=True)])
        m = L.scan_codex(self.root)
        coverage = L.verification_coverage(m)
        self.assertEqual((coverage['edited_sessions'], coverage['any_edit_then_verify_sessions']), (1, 1))
        self.assertEqual(coverage['final_edit_verified_sessions'], 0)
        self.assertEqual(coverage['final_edit_without_verification_sessions'], 1)
        self.assertEqual(coverage['final_edit_success_coverage'], 0)

    def test_latest_verification_return_sets_final_status(self):
        for name, code in (('passed', 0), ('failed', 1), ('unknown', None)):
            rows = [call('apply_patch', 'patch', 'edit', custom=True),
                    call('exec_command', {'cmd': 'pytest'}, 'first'), self.output('first'),
                    call('exec_command', {'cmd': 'make'}, 'latest')]
            if code is not None:
                rows.append(self.output('latest', code))
            self.codex(rows, name=name)
        coverage = L.verification_coverage(L.scan_codex(self.root))
        self.assertEqual(coverage['edited_sessions'], 3)
        self.assertEqual(coverage['final_edit_verified_sessions'], 3)
        for name in ('passed', 'failed', 'unknown'):
            self.assertEqual(coverage[f'final_edit_verification_{name}_sessions'], 1)
        self.assertEqual(coverage['categories']['build'], {'attempts': 3, 'passed': 1, 'failed': 1, 'unknown': 1})
        self.assertEqual(coverage['verification_attempts'], 6)
        self.assertEqual(coverage['verification_passed'], 4)

    def test_missing_timestamps_cannot_prove_final_order(self):
        self.codex([call('apply_patch', 'patch', 'edit', custom=True, ts=None),
                    call('exec_command', {'cmd': 'pytest'}, 'test'), self.output('test')])
        coverage = L.verification_coverage(L.scan_codex(self.root))
        self.assertEqual(coverage['final_edit_verified_sessions'], 0)
        self.assertEqual(coverage['final_edit_verification_unknown_sessions'], 1)
        self.assertEqual(coverage['final_edit_order_unknown_sessions'], 1)

    def test_unedited_sessions_do_not_enter_denominator_and_merge_keeps_scopes(self):
        self.codex([call('exec_command', {'cmd': 'pytest'})])
        empty = L.verification_coverage(L.scan_codex(self.root))
        self.assertEqual(empty['edited_sessions'], 0)
        self.assertIsNone(empty['final_edit_verification_coverage'])
        self.write('projects/a.jsonl', [assistant(tools=[('Edit', {})])])
        combined = L.verification_coverage(L.merge_metrics([L.scan(self.root), L.scan_codex(self.root)]))
        self.assertEqual(combined['edited_sessions'], 1)
        self.assertEqual(combined['final_edit_verified_sessions'], 0)

    def test_call_ids_are_scoped_to_sessions(self):
        self.codex([call('exec_command', {'cmd': 'pytest'}), self.output('call-1')], name='one')
        self.codex([call('exec_command', {'cmd': 'pytest'}), self.output('call-1', 1)], name='two')
        summary = L.scan_codex(self.root).history.summary()
        self.assertEqual((summary['verification_calls'], summary['verification_passed'], summary['verification_failed']), (2, 1, 1))

    def test_recorder_finish_exit_two_is_unknown_not_failed(self):
        rows = []
        commands = ('.venv/bin/agent-level-record', './agent-level record',
                    'python3 agent_level_record.py', '/venv/bin/python3 -m agent_level_record')
        for index, command in enumerate(commands):
            for result, code in (('passed', 0), ('failed', 1), ('unknown', 2)):
                cid = f'{index}-{result}'
                rows += [call('exec_command', {'cmd': command + ' finish --task-dir /t'}, cid),
                         self.output(cid, code)]
        rows.append(call('exec_command', {'cmd': 'agent-level-record finish --task-dir /t --unknown blocked'}, 'skipped'))
        self.codex(rows)
        summary = L.scan_codex(self.root).history.summary()
        self.assertEqual((summary['verification_calls'], summary['verification_passed'],
                          summary['verification_failed'], summary['verification_unknown']), (12, 4, 4, 4))

    def test_recorder_text_in_test_arguments_does_not_change_exit_two(self):
        self.codex([call('exec_command', {'cmd': 'pytest -k "agent-level-record finish"'}, 'test'),
                    self.output('test', 2)])
        summary = L.scan_codex(self.root).history.summary()
        self.assertEqual(summary['verification_failed'], 1)
        self.assertEqual(summary['verification_unknown'], 0)

    def test_claude_recorder_exit_code_comes_from_error_result(self):
        rows = []
        for index, content in enumerate(('Exit code 1\nfailed', 'Exit code 2\nunknown',
                                         [{'type': 'text', 'text': 'Exit code 2'}])):
            use = assistant(tools=[('Bash', {'command': 'agent-level record finish --task-dir /t'})])
            use['message']['content'][1]['id'] = f'finish-{index}'
            rows += [use, user([{'type': 'tool_result', 'tool_use_id': f'finish-{index}',
                                 'is_error': True, 'content': content}])]
        rows += [assistant(tools=[('Bash', {'command': 'make'})]),
                 user([{'type': 'tool_result', 'tool_use_id': 't', 'is_error': True, 'content': 'Exit code 2'}])]
        self.write('projects/a.jsonl', rows)
        summary = L.scan(self.root).history.summary()
        self.assertEqual((summary['verification_calls'], summary['verification_failed'],
                          summary['verification_unknown']), (4, 2, 2))


class TestStructuredCodexLogs(TempCase):
    def test_explicit_complete_nested_trace_can_expose_edit_and_verify(self):
        output = {'nested_tool_calls_complete': True, 'nested_tool_calls': [
            {'type': 'custom_tool_call', 'call_id': 'edit', 'name': 'apply_patch', 'input': 'PRIVATE_PATCH',
             'timestamp': '2026-09-10T10:00:00Z'},
            {'call_id': 'verify', 'name': 'exec_command', 'arguments': {'cmd': 'pytest PRIVATE_ARGUMENT'},
             'timestamp': '2026-09-10T10:01:00Z', 'output': {'exit_code': 0}}]}
        rows = [call('exec', 'PRIVATE_DYNAMIC_JS', custom=True),
                record('response_item', {'type': 'custom_tool_call_output', 'call_id': 'call-1', 'output': output})]
        self.codex(rows)
        self.codex(rows, archive=True)
        metrics = L.scan_codex(self.root)
        visibility = L.observability(metrics)
        self.assertEqual(metrics.tool_calls, 3)
        self.assertEqual(visibility['structured_nested_tool_calls'], 2)
        self.assertEqual(visibility['opaque_orchestrator_calls'], 0)
        self.assertEqual(visibility['orchestrator_expansion_ratio'], 1)
        self.assertEqual(L.verification_coverage(metrics)['final_edit_verification_passed_sessions'], 1)
        self.assertNotIn('PRIVATE_', json.dumps([visibility, L.verification_coverage(metrics), L.usage_breakdown(metrics)]))

    def test_partial_nested_trace_keeps_orchestrator_opaque(self):
        self.codex([call('exec', 'PRIVATE_JS', custom=True), record('response_item', {
            'type': 'custom_tool_call_output', 'call_id': 'call-1', 'output': {'nested_tool_calls': [
                {'call_id': 'test', 'name': 'exec_command', 'arguments': {'cmd': 'pytest'},
                 'timestamp': '2026-09-10T10:00:00Z', 'output': {'exit_code': 0}}]}})])
        visibility = L.observability(L.scan_codex(self.root))
        self.assertEqual(visibility['status'], 'partial')
        self.assertEqual(visibility['structured_nested_tool_calls'], 1)
        self.assertEqual(visibility['opaque_orchestrator_calls'], 1)

    def test_typed_begin_end_fallback_and_canonical_mirrors_are_deduplicated(self):
        self.codex([call('exec', 'PRIVATE_JS', custom=True),
                    record('event_msg', {'type': 'exec_command_begin', 'call_id': 'inner',
                                         'parent_call_id': 'call-1', 'command': ['pytest', '-q']}),
                    record('event_msg', {'type': 'exec_command_end', 'call_id': 'inner', 'exit_code': 1}),
                    call('exec_command', {'cmd': 'make'}, 'direct'),
                    record('event_msg', {'type': 'exec_command_begin', 'call_id': 'direct', 'command': ['make']}),
                    record('response_item', {'type': 'function_call_output', 'call_id': 'direct', 'output': {'exit_code': 0}})])
        metrics = L.scan_codex(self.root)
        summary = metrics.history.summary()
        self.assertEqual(metrics.tool_calls, 3)
        self.assertEqual((summary['verification_calls'], summary['verification_passed'], summary['verification_failed']), (2, 1, 1))
        self.assertEqual(metrics.diagnostics['structured_nested_tool_calls'], 1)

    def completed(self, kind, cid, ts, started=None, **item):
        payload = {'type': 'item_completed', 'item': {'type': kind, 'id': cid, **item}}
        if started is not None:
            payload['started_at_ms'] = int(L.record_ts({'timestamp': started}).timestamp() * 1000)
        return record('event_msg', payload, ts)

    def test_completed_items_inside_code_orchestration_expose_edit_and_verify(self):
        rows = [call('exec', 'PRIVATE_JS', custom=True),
                self.completed('FileChange', 'edit', '2026-09-10T10:00:01Z', status='completed',
                               changes={'PRIVATE_PATH': {'type': 'update'}}),
                self.completed('FileChange', 'rejected', '2026-09-10T10:00:01Z', status='declined', changes={}),
                self.completed('CommandExecution', 'test', '2026-09-10T10:00:03Z', '2026-09-10T10:00:02Z',
                               command=['/bin/bash', '-lc', 'pytest PRIVATE_ARGUMENT'], status='completed', exit_code=0),
                self.completed('CommandExecution', 'denied', '2026-09-10T10:00:03Z', command='make', status='declined'),
                record('response_item', {'type': 'custom_tool_call_output', 'call_id': 'call-1',
                                         'output': 'PRIVATE_OUTPUT'}, '2026-09-10T10:00:04Z'),
                self.completed('CommandExecution', 'background', '2026-09-10T10:05:00Z', '2026-09-10T10:00:03Z',
                               command='bash scripts/fast_build.sh --release', status='failed', exit_code=2)]
        self.codex(rows)
        self.codex(rows, archive=True)
        metrics = L.scan_codex(self.root)
        visibility = L.observability(metrics)
        coverage = L.verification_coverage(metrics)
        self.assertEqual((metrics.tool_calls, metrics.edit_calls), (4, 1))
        self.assertEqual((metrics.bash['test'], metrics.bash['build']), (1, 1))
        self.assertEqual(visibility['structured_nested_tool_calls'], 3)
        self.assertEqual(visibility['opaque_orchestrator_calls'], 1)
        self.assertEqual((coverage['verification_passed'], coverage['verification_failed']), (1, 1))
        self.assertEqual(coverage['final_edit_verification_failed_sessions'], 1)
        self.assertNotIn('PRIVATE_', json.dumps([visibility, coverage, L.usage_breakdown(metrics)]))

    def test_completed_item_mirrors_of_canonical_calls_count_once(self):
        self.codex([self.completed('CommandExecution', 'direct', '2026-09-10T10:00:00Z', command='pytest',
                                   status='completed', exit_code=0),
                    self.completed('FileChange', 'patch', '2026-09-10T10:00:00Z', status='completed',
                                   changes={'a': {}}),
                    call('exec_command', {'cmd': 'pytest'}, 'direct'),
                    record('response_item', {'type': 'function_call_output', 'call_id': 'direct',
                                             'output': {'exit_code': 0}}),
                    call('apply_patch', 'patch', 'patch', custom=True)])
        metrics = L.scan_codex(self.root)
        self.assertEqual((metrics.tool_calls, metrics.edit_calls), (2, 1))
        self.assertEqual(metrics.diagnostics['structured_nested_tool_calls'], 0)
        self.assertEqual(metrics.history.summary()['verification_calls'], 1)

    def test_background_command_started_before_final_edit_does_not_verify_it(self):
        self.codex([call('exec', 'js', custom=True),
                    record('response_item', {'type': 'custom_tool_call_output', 'call_id': 'call-1',
                                             'output': ''}, '2026-09-10T10:00:01Z'),
                    call('exec', 'js', 'call-2', custom=True, ts='2026-09-10T10:01:00Z'),
                    self.completed('FileChange', 'edit', '2026-09-10T10:01:01Z', status='completed',
                                   changes={'a': {}}),
                    record('response_item', {'type': 'custom_tool_call_output', 'call_id': 'call-2',
                                             'output': ''}, '2026-09-10T10:01:02Z'),
                    self.completed('CommandExecution', 'build', '2026-09-10T10:02:00Z', '2026-09-10T10:00:00.500Z',
                                   command='make', status='completed', exit_code=0)])
        coverage = L.verification_coverage(L.scan_codex(self.root))
        self.assertEqual((coverage['edited_sessions'], coverage['any_edit_then_verify_sessions']), (1, 0))
        self.assertEqual(coverage['final_edit_verified_sessions'], 0)

    def test_public_jsonl_started_completed_calls_results_and_usage(self):
        self.write('sessions/public.jsonl', [
            {'type': 'thread.started', 'thread_id': 'public'},
            {'type': 'item.completed', 'item': {'id': 'edit', 'type': 'file_change', 'changes': [{'path': 'PRIVATE_PATH', 'kind': 'update'}]}},
            {'type': 'item.started', 'item': {'id': 'command', 'type': 'command_execution', 'command': 'pytest'}},
            {'type': 'item.completed', 'item': {'id': 'command', 'type': 'command_execution', 'command': 'pytest', 'exit_code': 0}},
            {'type': 'item.completed', 'item': {'id': 'reply', 'type': 'agent_message', 'text': 'PRIVATE_TEXT'}},
            {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 40, 'output_tokens': 10}}])
        metrics = L.scan_codex(self.root)
        self.assertEqual((metrics.tool_calls, metrics.edit_calls, metrics.assistant), (2, 1, 1))
        self.assertEqual(metrics.history.summary()['verification_passed'], 1)
        self.assertEqual((metrics.input_tokens, metrics.cache_read, metrics.output_tokens), (100, 40, 10))
        self.assertEqual(L.verification_coverage(metrics)['final_edit_order_unknown_sessions'], 1)
        self.assertEqual(L.observability(metrics)['public_jsonl_tool_calls'], 2)

    def test_role_costs_use_metadata_and_preserve_unknown(self):
        for name, source, thread_source, model in (
                ('executor', 'cli', None, 'codex-auto-review'),
                ('auto_review', 'cli', 'guardian_review', 'GPT-6'),
                ('subagent', {'subagent': {'other': 'worker'}}, None, 'GPT-6'),
                ('unknown', None, None, 'GPT-6')):
            self.write(f'sessions/{name}.jsonl', [
                record('session_meta', {'id': name, 'source': source, 'thread_source': thread_source}),
                record('turn_context', {'model': model}), tokens(100, 40, 10)])
        metrics = L.scan_codex(self.root)
        usage = L.usage_breakdown(metrics)
        self.assertEqual({row['role'] for row in usage['roles']}, {'executor', 'auto_review', 'subagent', 'unknown'})
        self.assertEqual(sum(row['total_tokens'] for row in usage['roles']), metrics.input_tokens + metrics.output_tokens)
        self.assertTrue(all(row['uncached_input_tokens'] == 60 for row in usage['roles']))
        merged = L.usage_breakdown(L.merge_metrics([metrics, L.Metrics('claude')]))
        self.assertEqual(merged['roles'], usage['roles'])
        self.assertEqual(len(merged['daily_roles']), 4)

    def test_public_repeated_turns_and_archive_replays_keep_usage_and_final_end(self):
        rows = [{'type': 'thread.started', 'thread_id': 'public'}]
        for index in range(2):
            rows.extend([
                {'type': 'item.completed', 'item': {'id': f'reply-{index}', 'type': 'agent_message', 'text': 'same reply'}},
                {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 40, 'output_tokens': 10}}])
        self.write('sessions/public.jsonl', rows)
        self.write('archived_sessions/public.jsonl', rows)
        metrics = L.scan_codex(self.root)
        self.assertEqual(metrics.assistant, 2)
        self.assertEqual(metrics.input_tokens, 200)
        self.assertEqual(metrics.history.summary()['ended_sessions'], 1)

    def test_public_missing_timestamps_are_disclosed_when_date_filter_excludes_records(self):
        self.write('sessions/public.jsonl', [
            {'type': 'thread.started', 'thread_id': 'public'},
            {'type': 'item.completed', 'item': {'id': 'command', 'type': 'command_execution', 'command': 'pytest', 'exit_code': 0}}])
        metrics = L.scan_codex(self.root, since=L.parse_date('2026-09-01'))
        self.assertEqual(metrics.tool_calls, 0)
        visibility = L.observability(metrics)
        self.assertEqual(visibility['status'], 'partial')
        self.assertEqual(visibility['missing_timestamp_records'], 1)


class TestRulesAndMerge(TempCase):
    def test_large_read_only_trace_not_agent_engineering(self):
        m = L.Metrics()
        m.tool_calls, m.assistant, m.humanish_user = 1000, 200, 10
        m.tools['Task'] = 100
        self.assertEqual(A.evaluate(m)['current'], 1)

    def test_no_data_defaults_to_l0(self):
        self.assertEqual(A.evaluate(L.Metrics())['current'], 0)


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

    def test_recorder_entrypoints_and_nonexecuting_options(self):
        for entrypoint in ('agent-level-record', '/venv/bin/agent-level-record',
                           './agent-level record', 'python3 agent_level_record.py',
                           'python3 /source/agent_level_record.py', 'python3 -m agent_level_record'):
            for suffix, expected in (('finish --task-dir /t', 'test'),
                                     ('finish --help', 'other'), ('finish -h', 'other'),
                                     ('finish --hel', 'other'),
                                     ('finish --task-dir /t --unknown blocked', 'other'),
                                     ('finish --task-dir /t --unknown=blocked', 'other'),
                                     ('finish --task-dir /t --unk=blocked', 'other'),
                                     ('start --criteria test -- pytest', 'other')):
                command = entrypoint + ' ' + suffix
                with self.subTest(command=command):
                    self.assertEqual(L.classify_bash(command), expected)
        self.assertEqual(L.classify_bash(
            'bash -lc "uv run python3 -m agent_level_record finish --task-dir /t"'), 'test')
        self.assertEqual(L.classify_bash('echo "python3 agent_level_record.py finish"'), 'read')

    def test_git_pr_ci_are_not_test_verification(self):
        self.write('projects/a.jsonl', [assistant(tools=[('Bash', {'command': 'git status'}),
                                                         ('Bash', {'command': 'gh pr list'})])])
        self.assertEqual(L.scan(self.root).verification_ratio, 0)

    def test_date_validation_and_one_day_includes_only_today(self):
        self.write('projects/a.jsonl', [assistant(ts='2026-09-09T23:59:59Z'), assistant(ts='2026-09-10T00:00:00Z')])
        base = ['--source', 'claude', '--claude-dir', str(self.root)]
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
        return ['--claude-dir', str(self.root / 'claude'), '--codex-dir', str(self.root)]

    def test_installed_command_defaults_to_current_project(self):
        cases = [
            ([], ['--project-dir', str(self.root)]),
            (['--format', 'json'], ['--project-dir', str(self.root), '--format', 'json']),
            (['--project-dir', str(self.root / 'other')], ['--project-dir', str(self.root / 'other')]),
            (['--eval-results=results.json'], ['--eval-results=results.json']),
        ]
        with patch.object(A.Path, 'cwd', return_value=self.root):
            for arguments, expected in cases:
                with self.subTest(arguments=arguments), \
                        patch.object(A.sys, 'argv', ['agent-level-assess', *arguments]), \
                        patch.object(A, 'main', return_value=0) as main:
                    self.assertEqual(A.project_cli(), 0)
                    main.assert_called_once_with(expected, default_method='levels')

    def test_progress_describes_stages_without_polluting_json_stdout(self):
        rc, output, error = self.cli(self.fixture() + ['--format', 'json'])
        self.assertEqual(rc, 0)
        self.assertIn('reports', json.loads(output))
        for stage in ('Reading task evaluation records', 'Scanning claude session logs',
                      'Scanning codex session logs', 'Calculating combined assessment',
                      'Generating JSON report'):
            self.assertIn(stage, error)
        self.assertNotRegex(error, r'[\u4e00-\u9fff]')
        self.assertNotIn('PRIVATE_', error)

    def test_scanning_progress_is_throttled_by_time(self):
        with patch.object(A.time, 'monotonic', side_effect=[0, 1, 2, 2.5]), \
                contextlib.redirect_stderr(io.StringIO()) as error:
            update = A.scan_progress('codex')
            update(1)
            update(2)
            update(3)
        self.assertEqual(error.getvalue().count('processing log file'), 1)
        self.assertIn('processing log file 2', error.getvalue())

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

    def test_html_is_bilingual_with_unique_control_targets(self):
        rc, html, _ = self.cli(self.fixture() + ['--format', 'html'])
        self.assertEqual(rc, 0)
        self.assertIn('<html lang="en">', html)
        self.assertIn('Selected period:', html)
        self.assertIn('Evaluation trial coverage:', html)
        self.assertIn('id="report-language"', html)
        self.assertIn('data-zh="评估方式"', html)
        self.assertIn('data-zh="等级要求与差距"', html)
        self.assertIn('data-zh="日常任务验收"', html)
        self.assertIn('data-zh="本地自我改进对照"', html)
        self.assertEqual(re.findall(r'<button role="tab" id="tab-([^\"]+)"', html),
                         ['claude', 'codex', 'combined'])
        self.assertIn('<option value="levels" selected ', html)
        self.assertNotIn('<option value="both" selected', html)
        self.assertEqual(html.count('data-method-view="anthropic" hidden'), 3)
        self.assertEqual(html.count('data-method-view="improvement" hidden'), 3)
        self.assertNotIn('data-method-view="levels" hidden', html)
        self.assertEqual(html.count('<main'), 1)
        ids = re.findall(r'\bid="([^"]+)"', html)
        self.assertEqual(len(ids), len(set(ids)))
        targets = re.findall(r'(?:aria-controls|aria-labelledby|data-panel|for)="([^"]+)"', html)
        self.assertTrue(set(targets).issubset(ids))

    def test_html_escapes_dynamic_content(self):
        m = L.Metrics()
        result = A.evaluate(m)
        report = A.build_report(m, result, None, None)
        report['note'] = '<script>alert("x")</script>'
        html = render_html({'reports': {'claude': report}, 'ruleset_version': '1.0', 'merge_note': 'test'})
        self.assertNotIn('<script>alert', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('data-zh="&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;"', html)

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
                    path = Path('out/agent_level/2026-09-21') / f'ai-engineering-assessment.{extension}'
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

    def test_default_html_and_explicit_dual_format(self):
        args = self.fixture()
        previous_cwd = Path.cwd()
        self.addCleanup(os.chdir, previous_cwd)
        os.chdir(self.root)
        with patch.object(A, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 9, 21, 0, 30)
            base = Path('out/agent_level/2026-09-21/ai-engineering-assessment')
            rc, output, err = self.cli(args, stdout=False)
            self.assertEqual((rc, output), (0, ''))
            html = base.with_suffix('.html')
            self.assertTrue(html.read_text().startswith('<!doctype html>'))
            self.assertIn('id="panel-combined"', html.read_text())
            self.assertIn('id="panel-claude"', html.read_text())
            self.assertIn('id="panel-codex"', html.read_text())
            self.assertFalse(base.with_suffix('.txt').exists())
            self.assertEqual(err.count('[ok] report written:'), 0)
            self.assertIn(f'[open in browser] {html.resolve().as_uri()}', err)
            self.assertEqual(err.rstrip().splitlines()[-1], f'[open in browser] {html.resolve().as_uri()}')
            self.assertRegex(err, r'\[progress\] Edit → verify sessions: Claude \d+; Codex \d+\n'
                                 r'\[progress\] Generating HTML report')
            self.assertNotIn('| Metric', err)
            self.assertNotRegex(err, r'[\u4e00-\u9fff]')

            rc, output, err = self.cli(args + ['--format', 'txt+html', '-o', 'custom/result.json'],
                                       stdout=False)
            self.assertEqual((rc, output), (0, ''))
            base = Path('custom/result')
            txt, html = base.with_suffix('.txt'), base.with_suffix('.html')
            self.assertIn('Current Level', txt.read_text())
            self.assertTrue(html.read_text().startswith('<!doctype html>'))
            self.assertIn(str(txt), err)
            self.assertIn(str(html), err)
            self.assertFalse(Path('custom/result.json').exists())

    def test_key_metrics_lists_sources_with_separators(self):
        def report(level, tools, opaque, edited, verified):
            return {'current_level': level, 'observed': {'engineering_sessions': verified},
                    'tool_observability': {'recognized_tool_calls': tools, 'opaque_orchestrator_calls': opaque},
                    'verification_coverage': {'edited_sessions': edited}}
        metrics = A.render_key_metrics({'combined': report(4, 9716, 1725, 25, 3),
                                      'claude': report(4, 7941, 0, 25, 3),
                                      'codex': report(1, 1775, 1725, 0, 0)})
        self.assertEqual(metrics.splitlines(), [
            'Level: Claude L4; Codex L1',
            'Recognized tool calls: Claude 7,941; Codex 1,775',
            'Opaque orchestration calls: Claude 0; Codex 1,725',
            'Sessions with edits: Claude 25; Codex 0',
            'Edit → verify sessions: Claude 3; Codex 0'])
        self.assertIn('Level: Combined Unknown', A.render_key_metrics({'combined': report(None, 0, 0, 0, 0)}))

    def test_report_name_sets_title_and_default_filename(self):
        args = self.fixture()
        previous_cwd = Path.cwd()
        self.addCleanup(os.chdir, previous_cwd)
        os.chdir(self.root)
        with patch.object(A, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 9, 21, 0, 30)
            rc, output, _ = self.cli(args + ['--report-name', 'Team & Project Review'], stdout=False)
        self.assertEqual((rc, output), (0, ''))
        base = Path('out/agent_level/2026-09-21/team-project-review')
        self.assertFalse(base.with_suffix('.txt').exists())
        html = base.with_suffix('.html').read_text()
        self.assertRegex(html, r'<h1><span[^>]*>Team &amp; Project Review</span></h1>')
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
        self.assertRegex(html, r'<h1><span[^>]*>Team Review</span></h1>')
        self.assertIn('download="my-report.json"', html)

    def test_dual_format_stdout_requires_single_format(self):
        rc, output, err = self.cli(self.fixture() + ['--format', 'txt+html'])
        self.assertEqual((rc, output), (2, ''))
        self.assertIn('single --format', err)
        self.assertFalse((self.root / '-').exists())

    def test_default_html_can_write_to_stdout(self):
        rc, output, err = self.cli(self.fixture())
        self.assertEqual(rc, 0)
        self.assertTrue(output.startswith('<!doctype html>'))
        self.assertIn('Generating HTML report', err)

    def test_html_requested_range_and_actual_coverage(self):
        self.write('claude/projects/a.jsonl', [user('hi', ts='2026-09-10T10:00:00Z')])
        self.codex([message('user', ts='2026-09-12T10:00:00Z')])
        args = ['--claude-dir', str(self.root / 'claude'), '--codex-dir', str(self.root),
                '--format', 'html']
        cases = [([], 'All logs (no date filter)', True),
                 (['--since', '2026-09-01', '--until', '2026-09-20'],
                  '2026-09-01 to 2026-09-20', True),
                 (['--since', '2026-09-01'], '2026-09-01 to Any date', True),
                 (['--until', '2026-09-20'], 'Any date to 2026-09-20', True),
                 (['--since', '2026-10-01'], '2026-10-01 to Any date', False)]
        for extra, requested, has_data in cases:
            with self.subTest(args=extra):
                rc, html, _ = self.cli(args + extra)
                self.assertEqual(rc, 0)
                self.assertEqual(html.count('>Selected period: ' + requested + '</span>'), 3)
                if has_data:
                    for coverage in ('2026-09-10 to 2026-09-12',
                                     '2026-09-10 to 2026-09-10',
                                     '2026-09-12 to 2026-09-12'):
                        self.assertIn('Observed log coverage: ' + coverage + ' · UTC', html)
                else:
                    self.assertEqual(html.count('>Observed log coverage: No valid timestamps'), 3)

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
                                  '--codex-dir', str(self.root), '--format', 'json'])
        self.assertEqual(rc, 0)
        self.assertEqual(set(json.loads(output)['reports']), {'combined', 'claude', 'codex'})


if __name__ == '__main__':
    unittest.main()
