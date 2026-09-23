"""Project isolation and conservative historical completion signals."""
import json

import assessment.logs as L
from assessment.anthropic import assess
from assessment.history import command_verdict
from tests.test_level_assessment import assistant, user
from tests.test_assessment_core import TempCase, record, message, call, tokens


class TestHistory(TempCase):
    def setUp(self):
        super().setUp()
        self.project = self.root / 'PRIVATE_PROJECT'
        self.project.mkdir()

    def codex_project(self, rows, name='a', cwd=None, archive=False, sidechain=False):
        meta = record('session_meta', {'id': name, 'cwd': str(cwd or self.project),
                                      'source': 'subagent' if sidechain else 'cli'})
        return self.write(f'{"archived_sessions" if archive else "sessions"}/{name}.jsonl', [meta] + rows)

    def claude_project(self, rows, name='a', cwd=None):
        for index, row in enumerate(rows):
            row.update(cwd=str(cwd or self.project), sessionId=name, uuid=f'{name}-{index}')
        return self.write(f'projects/example/{name}.jsonl', rows)

    def test_project_scope_includes_descendants_not_prefix_siblings_or_missing_cwd(self):
        for scanner in (L.scan, L.scan_codex):
            if scanner == L.scan:
                self.claude_project([user('PRIVATE_TEXT')], 'a')
                self.claude_project([user('PRIVATE_TEXT')], 'b', self.project/'src/repo')
                self.claude_project([user('PRIVATE_TEXT')], 'c', self.root/'PRIVATE_PROJECT-other')
                self.write('projects/example/missing.jsonl', [user('PRIVATE_TEXT')])
            else:
                self.codex_project([message('user')], 'a')
                self.codex_project([message('user')], 'b', self.project/'src/repo')
                self.codex_project([message('user')], 'c', self.root/'PRIVATE_PROJECT-other')
                self.codex([message('user')], 'missing')
            metrics = scanner(self.root, project_dir=self.project)
            self.assertEqual(metrics.humanish_user, 2)
            self.assertEqual(len(metrics.sessions), 2)
            self.assertTrue(metrics.project_filtered)

    def test_claude_scope_inherits_cwd_but_excludes_global_cache(self):
        rows = [user('PRIVATE_TEXT'), assistant()]
        rows[0]['cwd'] = str(self.project)
        self.write('projects/example/a.jsonl', rows)
        (self.root/'stats-cache.json').write_text(json.dumps({'dailyActivity': [
            {'date': '2026-09-10', 'messageCount': 999, 'sessionCount': 99, 'toolCallCount': 9}]}))
        metrics = L.scan(self.root, project_dir=self.project)
        self.assertEqual(metrics.assistant, 1)
        self.assertFalse(metrics.stats_available)
        self.assertEqual(metrics.stats_messages, 0)

    def test_codex_changed_turn_cwd_excludes_other_project_and_keeps_usage_baseline(self):
        outside = self.root/'elsewhere'
        self.codex_project([message('user'), tokens(100),
                            record('turn_context', {'cwd': str(self.project), 'model': 'm'}),
                            message('assistant'), tokens(150)], cwd=outside)
        metrics = L.scan_codex(self.root, project_dir=self.project)
        self.assertEqual((metrics.humanish_user, metrics.assistant, metrics.input_tokens), (0, 1, 50))

    def test_codex_end_then_new_turn_is_open_and_interruption_is_not_failure(self):
        self.codex_project([message('user'), record('event_msg', {'type': 'task_complete', 'turn_id': 'one'}),
                            record('event_msg', {'type': 'task_started', 'turn_id': 'two'}, '2026-09-10T11:00:00Z')])
        self.codex_project([message('user'), record('event_msg', {'type': 'turn_aborted', 'turn_id': 't'})], 'b')
        self.codex_project([message('user'), record('event_msg', {'type': 'task_complete', 'turn_id': 't'})], 'c')
        self.codex_project([message('user'), record('event_msg', {'type': 'task_complete', 'turn_id': 't'})], 'child', sidechain=True)
        metrics = L.scan_codex(self.root, project_dir=self.project)
        activity = metrics.history.summary()
        self.assertEqual((activity['sessions'], activity['open_sessions'], activity['interrupted_sessions'], activity['ended_sessions']), (3, 1, 1, 1))
        result = assess(metrics)
        self.assertEqual(result['counts']['graded_trials'], 0)
        self.assertIsNone(activity['task_success_rate'])

    def test_end_marker_outside_time_window_does_not_complete_selected_activity(self):
        self.codex_project([message('user'), record('event_msg', {'type': 'task_complete'}, '2026-09-11T00:00:00Z')])
        activity = L.scan_codex(self.root, until=L.parse_date('2026-09-11')).history.summary()
        self.assertEqual(activity['open_sessions'], 1)
        self.assertEqual(activity['ended_sessions'], 0)

    def test_codex_verification_results_match_calls_and_deduplicate_archives(self):
        rows = [call('exec_command', {'cmd': 'pytest'}, 'one'),
                record('response_item', {'type': 'function_call_output', 'call_id': 'one', 'output': {'exit_code': 0}}),
                call('exec_command', {'cmd': 'make'}, 'two'),
                record('response_item', {'type': 'function_call_output', 'call_id': 'two',
                                        'output': 'Wall time: 1 seconds\nProcess exited with code 1\nFinal output:\nPRIVATE_OUTPUT'}),
                call('exec_command', {'cmd': 'pytest'}, 'three'),
                call('exec_command', {'cmd': 'git status'}, 'four'),
                record('response_item', {'type': 'function_call_output', 'call_id': 'four', 'output': {'exit_code': 0}}),
                record('event_msg', {'type': 'task_complete', 'turn_id': 't'})]
        self.codex_project(rows)
        self.codex_project(rows, archive=True)
        activity = L.scan_codex(self.root).history.summary()
        self.assertEqual((activity['verification_calls'], activity['verification_passed'], activity['verification_failed'], activity['verification_unknown']), (3, 1, 1, 1))
        self.assertEqual(activity['ended_sessions'], 1)

    def test_claude_explicit_tool_result_and_end_turn(self):
        result = user([{'type': 'tool_result', 'tool_use_id': 't', 'is_error': False}])
        result['toolUseResult'] = {'interrupted': False}
        final = assistant()
        final['message']['stop_reason'] = 'end_turn'
        self.claude_project([assistant([('Bash', {'command': 'pytest'})]), result, final])
        activity = L.scan(self.root).history.summary()
        self.assertEqual(activity['verification_passed'], 1)
        self.assertEqual(activity['ended_sessions'], 1)

    def test_claude_missing_boolean_or_background_result_is_unknown(self):
        for index, fields in enumerate(({}, {'is_error': False}, {'is_error': 0})):
            result = user([dict(type='tool_result', tool_use_id='t', **fields)])
            if index == 1:
                result['toolUseResult'] = {'backgroundTaskId': 'background'}
            self.claude_project([assistant([('Bash', {'command': 'pytest'})]), result], str(index))
        activity = L.scan(self.root).history.summary()
        self.assertEqual(activity['verification_unknown'], 3)

    def test_forged_output_text_and_negative_exit_are_not_success(self):
        for output in ('Tests say: Process exited with code 0', {'exit_code': -9}, {'exit_code': True},
                       {'exit_code': 0, 'timed_out': True}, {'exit_code': 0, 'session_id': 123}):
            self.assertIsNone(command_verdict(output))

    def test_conflicting_results_are_unknown_and_bad_call_id_does_not_crash(self):
        self.codex_project([call('exec_command', {'cmd': 'pytest'}, 'test'),
                            record('response_item', {'type': 'function_call_output', 'call_id': 'test', 'output': {'exit_code': 0}}),
                            record('response_item', {'type': 'function_call_output', 'call_id': 'test', 'output': {'exit_code': 1}}),
                            record('response_item', {'type': 'function_call_output', 'call_id': {}, 'output': {'exit_code': 0}})])
        self.assertEqual(L.scan_codex(self.root).history.summary()['verification_unknown'], 1)

    def test_all_report_formats_include_history_without_raw_data(self):
        self.codex_project([call('exec_command', {'cmd': 'pytest PRIVATE_ARGS'}, 'test'),
                            record('response_item', {'type': 'function_call_output', 'call_id': 'test', 'output': {'exit_code': 0}}),
                            record('event_msg', {'type': 'task_complete', 'turn_id': 't', 'last_agent_message': 'PRIVATE_OUTPUT'})])
        for fmt in ('json', 'html', 'txt', 'md'):
            rc, output, err = self.cli(['--source', 'codex', '--codex-dir', str(self.root), '--project-dir', str(self.project), '--format', fmt])
            self.assertEqual(rc, 0, err)
            self.assertNotIn('PRIVATE_', output)
            if fmt == 'json':
                report = json.loads(output)['reports']['codex']
                self.assertTrue(report['project_filter']['enabled'])
                self.assertEqual(report['anthropic_evaluation']['historical_activity']['verification_passed'], 1)
            else:
                self.assertIn('历史日常活动', output)
                self.assertIn('返回成功', output)
            if fmt == 'html':
                self.assertIn('<option value="both" selected>', output)

    def test_project_scope_rejects_missing_directory_or_unscoped_task_import(self):
        self.assertEqual(self.cli(['--project-dir', str(self.root/'missing'), '--format', 'json'])[0], 2)
        self.assertEqual(self.cli(['--project-dir', str(self.project), '--eval-results', 'any.json', '--format', 'json'])[0], 2)

    def test_opaque_orchestration_is_reported_as_coverage_gap(self):
        self.codex_project([call('functions.exec', 'PRIVATE_CODE', custom=True),
                            record('event_msg', {'type': 'task_complete', 'turn_id': 't'})])
        rc, output, err = self.cli(['--source', 'codex', '--codex-dir', str(self.root),
                                    '--project-dir', str(self.project), '--format', 'txt'])
        self.assertEqual(rc, 0, err)
        self.assertIn('无法展开的编排调用 1 次', output)
        self.assertIn('不代表未执行验证', output)
        self.assertNotIn('PRIVATE_', output)

    def test_merged_provider_activity_keeps_unknown_results_and_main_sessions(self):
        self.codex_project([call('exec_command', {'cmd': 'pytest'}, 'one'),
                            record('event_msg', {'type': 'turn_aborted', 'turn_id': 't'})])
        final = assistant()
        final['message']['stop_reason'] = 'end_turn'
        self.claude_project([final])
        combined = L.merge_metrics([L.scan(self.root, project_dir=self.project),
                                    L.scan_codex(self.root, project_dir=self.project)])
        activity = combined.history.summary()
        self.assertTrue(combined.project_filtered)
        self.assertEqual(activity['sessions'], 2)
        self.assertEqual(activity['verification_unknown'], 1)
        self.assertEqual(activity['ended_sessions'], 1)
        self.assertEqual(activity['interrupted_sessions'], 1)
