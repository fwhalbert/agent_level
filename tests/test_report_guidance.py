"""Gap presentation must preserve evidence and remain offline and bilingual."""
import copy
from pathlib import Path
import unittest

import assess
from assessment.guidance import EXPERIMENT_NOTE, recommended_experiment
from assessment.logs import Metrics, scan_codex
from assessment.web import render_html
from assessment.web_i18n import ZH
from examples.generate_report import sample_bundle


class TestReportGuidance(unittest.TestCase):
    def report_for_level(self, level):
        if level < 3:
            metrics = Metrics('codex')
            metrics.assistant = int(level > 0)
            metrics.edit_calls = int(level > 1)
        else:
            fixtures = Path(__file__).resolve().parents[1] / 'examples/sample-data/codex'
            metrics = scan_codex(fixtures, None, None)
            if level == 3:
                metrics.engineering_sessions = set(sorted(metrics.engineering_sessions)[:1])
        report = assess.build_report(metrics, assess.evaluate(metrics), None, None)
        self.assertEqual(report['current_level'], level)
        return report

    def test_all_observable_levels_have_translated_optional_experiment(self):
        for level in range(5):
            with self.subTest(level=level):
                report = self.report_for_level(level)
                before = copy.deepcopy(report)
                bundle = sample_bundle()
                bundle['reports']['codex'] = report
                html = render_html(bundle)
                text = assess.render_report(report)
                experiment = recommended_experiment(report)
                self.assertTrue(experiment)
                self.assertIn(experiment, text)
                self.assertIn(ZH[experiment], html)
                self.assertIn(f'Gap to next level · L{level + 1}', html)
                self.assertIn('缺少的证据', html)
                self.assertIn(EXPERIMENT_NOTE, text)
                self.assertEqual(report, before)
                for higher in (5, 6, 7):
                    self.assertEqual(report['levels'][f'L{higher}']['status'], 'NOT VERIFIED')

    def test_gap_lists_missing_checks_without_claiming_passed_checks_are_missing(self):
        bundle = sample_bundle()
        report = self.report_for_level(3)
        bundle['reports']['codex'] = report
        html = render_html(bundle)
        gap = html.split('class="card next-level-gap"', 1)[1].split('class="model-usage"', 1)[0]
        self.assertIn('edit followed by build/test in &gt;= 3 sessions', gap)
        self.assertNotIn('edit/verify activity across &gt;= 2 UTC days', gap)

    def test_gap_content_is_escaped_and_l5_remains_explicitly_unverified(self):
        bundle = sample_bundle()
        bundle['reports']['codex']['gaps'][0]['check'] = '<script>unsafe</script>'
        html = render_html(bundle)
        self.assertNotIn('<script>unsafe</script>', html)
        self.assertIn('&lt;script&gt;unsafe&lt;/script&gt;', html)
        self.assertIn('L5 remains unverified by this analyzer.', html)

    def test_final_edit_coverage_displays_denominator_and_unknown_results(self):
        bundle = sample_bundle()
        report = bundle['reports']['codex']
        report['verification_coverage'] = dict(
            edited_sessions=2, any_edit_then_verify_sessions=2,
            final_edit_verified_sessions=1, final_edit_verification_passed_sessions=0,
            final_edit_verification_failed_sessions=0, final_edit_verification_unknown_sessions=1,
            final_edit_without_verification_sessions=1,
            final_edit_verification_coverage=.5, final_edit_success_coverage=0)
        report['tool_observability'] = dict(
            recognized_tool_calls=10, structured_nested_tool_calls=5, public_jsonl_tool_calls=5,
            expanded_orchestrator_calls=1, orchestrator_calls=2, opaque_orchestrator_calls=1,
            unparsed_records=3, missing_timestamp_records=4,
            may_undercount_edits_and_verification=True)
        html = render_html(bundle)
        panel = html.split('class="card verification-coverage"', 1)[1].split('class="card next-level-gap"', 1)[0]
        self.assertIn('1 / 2 edited sessions attempted build / test', panel)
        self.assertIn('50.0%', panel)
        self.assertIn('0 / 2 edited sessions returned success', panel)
        self.assertIn('success 0 / failure 0 / unknown 1', panel)
        self.assertIn('Structured nested calls: 5', panel)
        self.assertIn('Orchestration calls expanded: 1 / 2', panel)
        self.assertIn('Unparsed records: 3', panel)
        self.assertIn('Records with missing timestamps: 4', panel)
        self.assertIn('A later edit invalidates earlier verification coverage', panel)
        self.assertIn('未识别到调用不代表未执行', panel)

    def test_no_observed_edits_has_unavailable_coverage_instead_of_zero_percent(self):
        from assessment.web import _verification_panel
        coverage = dict(edited_sessions=0, final_edit_verified_sessions=0,
                        final_edit_verification_passed_sessions=0, final_edit_verification_failed_sessions=0,
                        final_edit_verification_unknown_sessions=0, final_edit_without_verification_sessions=0,
                        final_edit_verification_coverage=None, final_edit_success_coverage=None)
        html = _verification_panel({'verification_coverage': coverage})
        self.assertNotIn('0.0%', html)
        self.assertEqual(html.count('<div class="value">—</div>'), 2)

    def test_acceptance_review_keeps_suggestions_and_missing_interventions_explicit(self):
        from assessment.web import _review_panel
        report = dict(
            counts=dict(trials=2, session_linked_trials=1, session_unlinked_trials=1),
            acceptance_standard_coverage=dict(tasks=1, frozen=1, reviewed=0, version_recorded=1, author_recorded=0),
            review_summary=dict(success_trials=1, failure_trials=1, unknown_trials=0,
                                reviewed_success_trials=0, reviewed_failure_trials=1,
                                reviewed_selection_counts={'all_failure': 1}, failure_categories={'tests': 1},
                                suggested_success_sample=1, suggested_failure_review=1, suggested_unknown_review=0),
            task_diagnostics=[dict(
                task_ref='task-' + 'a' * 16, group_id='group-' + 'b' * 16,
                record_ref='/private/PRIVATE_RECORD', acceptance_criteria='PRIVATE_CRITERIA',
                acceptance_standard=dict(frozen=True, reviewed=False, review_source='self', author='PRIVATE_AUTHOR'),
                trials=[dict(trial_ref='trial-' + 'c' * 16, status='failure', reason='acceptance_failed',
                             session_linked=True, session_ids=['PRIVATE_SESSION'],
                             human_review=dict(recorded=True, result='confirmed', failure_category='tests'),
                             human_interventions=dict(recorded=True, total=0, types={'clarification': 0})),
                        dict(trial_ref='trial-' + 'd' * 16, status='unknown', reason='timeout',
                             session_linked=False, human_review=dict(recorded=False),
                             human_interventions=dict(recorded=False, total=None))])])
        html = _review_panel(report)
        self.assertIn('Frozen acceptance definitions: 1 / 1', html)
        self.assertIn('Human or independent model review recorded: 0 / 1', html)
        self.assertIn('Acceptance trials linked to sessions: 1 / 2', html)
        self.assertIn('Suggestions and selection metadata do not prove human review occurred', html)
        self.assertIn('Suggested review count (tasks)', html)
        self.assertIn('Human reviewed / Recorded (trials)', html)
        self.assertIn('successful tasks within each evaluation group, rounded up', html)
        self.assertIn('Acceptance timeout', html)
        self.assertIn('验收超时', html)
        self.assertIn('Confirmed', html)
        self.assertIn('Tests', html)
        self.assertIn('Human review failure categories', html)
        self.assertIn('Clarification', html)
        self.assertIn('</td><td>0<br>', html)
        self.assertIn('Not recorded', html)
        self.assertNotIn('PRIVATE_', html)

    def test_new_groups_use_stable_ids_and_unknown_intervention_counts(self):
        from assessment.web import _anthropic_panel
        from assessment.anthropic import assess as assess_evals
        from tests.test_anthropic_eval import data, task
        report = sample_bundle()['reports']['codex']
        report['anthropic_evaluation'] = assess_evals(Metrics('codex'), data(task(source='codex')))
        group = report['anthropic_evaluation']['groups'][0]
        group['group_id'] = 'group-' + 'f' * 16
        group['label'] = 'Evaluation group 42'
        group['human_interventions'] = dict(recorded=0, total=None, missing=3)
        html = _anthropic_panel(report)
        self.assertIn('Evaluation group · group-' + 'f' * 16, html)
        self.assertNotIn('Evaluation group 42', html)
        self.assertIn('Human intervention records missing: 3', html)
        self.assertIn('Missing counts are unknown, not zero', html)
