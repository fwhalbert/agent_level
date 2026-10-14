"""Report integration for final-edit coverage, visibility and role usage."""
import contextlib
import io
import json
from pathlib import Path
import sys

import assess as A
import agent_level_record as R
import assessment.logs as L
from assessment.anthropic import assess as assess_tasks
from assessment.collection import load_project_evals
from assessment.web import render_html
from tests.test_assessment_core import TempCase, call, record, tokens


class TestWorkflowReporting(TempCase):
    def record_command(self, args):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
            status = R.main(args)
        return status, out.getvalue()

    def report(self, rows):
        self.codex(rows)
        metrics = L.scan_codex(self.root)
        return A.build_report(metrics, A.evaluate(metrics), None, None)

    def outputs(self, report):
        return (json.dumps(report), A.render_report(report),
                A.render_report(report, markdown=True),
                render_html({'reports': {'codex': report}, 'merge_note': 'Synthetic test',
                             'version': '1.0.0', 'ruleset_version': '1.0'}))

    def test_later_edit_invalidates_final_coverage_without_changing_level_signal(self):
        report = self.report([
            call('apply_patch', 'PRIVATE_PATCH', 'edit', custom=True),
            call('exec_command', {'cmd': 'pytest PRIVATE_COMMAND'}, 'verify',
                 ts='2026-09-10T10:01:00Z'),
            record('response_item', {'type': 'function_call_output', 'call_id': 'verify',
                                    'output': {'exit_code': 0}}, '2026-09-10T10:01:30Z'),
            call('apply_patch', 'PRIVATE_LATER_PATCH', 'later',
                 ts='2026-09-10T10:02:00Z', custom=True),
        ])
        self.assertEqual(report['observed']['engineering_sessions'], 1)
        coverage = report['verification_coverage']
        self.assertEqual(coverage['edited_sessions'], 1)
        self.assertEqual(coverage['final_edit_verification_coverage'], 0)
        self.assertEqual(coverage['final_edit_without_verification_sessions'], 1)
        self.assertEqual(coverage['verification_passed'], 1)
        for output in self.outputs(report):
            self.assertNotIn('PRIVATE_', output)
        for output in self.outputs(report)[1:3]:
            self.assertIn('Final edit verification coverage', output)
            self.assertIn('No verification after final edit: 1', output)

    def test_opaque_calls_are_partial_with_unknown_coverage_not_a_zero_claim(self):
        report = self.report([call('functions.exec', 'PRIVATE_CODE', custom=True)])
        self.assertIsNone(report['verification_coverage']['final_edit_verification_coverage'])
        visibility = report['tool_observability']
        self.assertEqual(visibility['status'], 'partial')
        self.assertEqual(visibility['opaque_orchestrator_calls'], 1)
        self.assertEqual(visibility['orchestrator_expansion_ratio'], 0)
        for output in self.outputs(report):
            self.assertNotIn('PRIVATE_', output)
        self.assertIn('unobserved calls are not zero calls', A.render_report(report))

    def test_source_recorder_finish_counts_after_final_edit(self):
        report = self.report([
            call('apply_patch', 'PRIVATE_PATCH', 'edit', custom=True),
            call('exec_command', {'cmd': 'python3 agent_level_record.py finish --task-dir /t'},
                 'verify', ts='2026-09-10T10:01:00Z'),
            record('response_item', {'type': 'function_call_output', 'call_id': 'verify',
                                    'output': {'exit_code': 0}}, '2026-09-10T10:01:30Z'),
            call('exec_command', {'cmd': 'agent-level-record finish --help'},
                 'help', ts='2026-09-10T10:02:00Z'),
        ])
        coverage = report['verification_coverage']
        self.assertEqual(coverage['verification_attempts'], 1)
        self.assertEqual(coverage['final_edit_verified_sessions'], 1)
        self.assertEqual(coverage['final_edit_verification_passed_sessions'], 1)
        self.assertEqual(coverage['final_edit_verification_coverage'], 1)

    def test_role_totals_include_cache_without_double_counting_reasoning(self):
        report = self.report([tokens(100, cached=80, out=10)])
        roles = report['model_usage']['roles']
        self.assertEqual(sum(row['total_tokens'] for row in roles), 110)
        self.assertEqual(sum(row['cache_read'] for row in roles), 80)
        self.assertEqual(sum(row['uncached_input_tokens'] for row in roles), 20)
        for output in self.outputs(report)[1:3]:
            self.assertIn('Token usage by role', output)
            self.assertIn('cache read 80', output)
            self.assertIn('not monetary costs', output)
        self.assertEqual(report['version'], '1.0.0')
        self.assertEqual(report['ruleset_version'], '1.0')

    def test_discovered_frozen_plan_review_and_local_lookup_preserve_verdict(self):
        status, output = self.record_command([
            'start', '--repo', str(self.root), '--source', 'codex',
            '--model', 'PRIVATE_MODEL', '--criteria', 'PRIVATE_CRITERIA',
            '--criteria-version', '1', '--criteria-author', 'PRIVATE_AUTHOR',
            '--session-id', 'PRIVATE_SESSION', '--', sys.executable, '-c', 'assert 2 + 2 == 4'])
        self.assertEqual(status, 0)
        directory = Path(output.strip())
        self.assertEqual(self.record_command(['finish', '--task-dir', str(directory)])[0], 0)
        original = json.loads((directory / 'results.json').read_text())['tasks'][0]['trials'][0]
        review = self.root / 'synthetic-review.json'
        review.write_text(json.dumps(dict(
            type='human', reviewer='PRIVATE_SYNTHETIC_REVIEWER',
            reviewed_at='2026-09-30T12:00:00+08:00', result='overturned',
            selection='random_success', failure_category='tests', human_interventions=1,
            interventions=[dict(type='correction', count=1, minutes=2)])))
        self.assertEqual(self.record_command([
            'review', '--task-dir', str(directory), '--review-file', str(review)])[0], 0)
        data, reader, _ = load_project_evals(self.root)
        evaluated = assess_tasks(L.Metrics('codex'), data, evidence_reader=reader)
        self.assertEqual(evaluated['counts']['successful_trials'], 1)
        self.assertEqual(evaluated['acceptance_standard_coverage']['frozen'], 1)
        self.assertEqual(evaluated['counts']['session_linked_trials'], 1)
        diagnostic = evaluated['task_diagnostics'][0]
        self.assertEqual(diagnostic['trials'][0]['human_review']['result'], 'overturned')
        self.assertEqual(diagnostic['trials'][0]['human_interventions']['total'], 1)
        self.assertNotIn('PRIVATE_', json.dumps(evaluated))
        updated = json.loads((directory / 'results.json').read_text())['tasks'][0]['trials'][0]
        for field in ('status', 'outcome', 'graders', 'transcript_ref', 'transcript_sha256'):
            self.assertEqual(original[field], updated[field])
        status, located = self.record_command([
            'locate', '--workspace', str(self.root), '--task-ref', diagnostic['task_ref']])
        self.assertEqual(status, 0)
        self.assertEqual(Path(located.strip()), directory)
