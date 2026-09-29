"""Outcome evidence, statistical estimates, isolation and integration regressions."""
import base64
import copy
import json
import re

import assess as A
from assessment.anthropic import assess, filter_evals, render_summary, task_effort
from assessment.logs import Metrics, merge_metrics, parse_date
from tests.test_assessment_core import TempCase, message


def task(outcomes=(True, True, True, False), source='claude', task_id='PRIVATE_TASK', **extra):
    return dict(source=source, suite_id='PRIVATE_SUITE', suite_version='1',
                model='PRIVATE_MODEL', harness_version='PRIVATE_HARNESS', task_id=task_id,
                acceptance_criteria='PRIVATE_CRITERIA', reference_solution_ref='PRIVATE_REFERENCE',
                required_graders=['tests'], planned_trials=len(outcomes),
                trials=[dict(trial_id=f'PRIVATE_TRIAL_{i}', timestamp='2026-09-10T10:00:00Z',
                             environment_reset=True, transcript_ref='PRIVATE_TRANSCRIPT',
                             graders=[dict(grader_id='tests', type='code', passed=passed,
                                           evidence_ref='PRIVATE_GRADER')],
                             outcome=dict(passed=passed, evidence_ref='PRIVATE_OUTCOME'))
                        for i, passed in enumerate(outcomes)], **extra)


def data(*tasks):
    return {'schema_version': '1.0', 'tasks': list(tasks)}


class TestAnthropic(TempCase):
    def test_logs_never_become_task_outcomes(self):
        m = Metrics()
        m.tool_calls, m.humanish_user, m.edit_calls = 1000, 10, 8
        m.engineering_sessions.update(('a', 'b', 'c'))
        m.engineering_days.update(('2026-09-09', '2026-09-10'))
        self.assertEqual(A.evaluate(m)['current'], 4)
        r = assess(m)
        self.assertEqual(r['status'], 'insufficient_evidence')
        self.assertEqual(r['counts']['graded_trials'], 0)
        self.assertEqual(r['groups'], [])
        self.assertFalse(r['official_certification'])

    def test_without_replacement_estimates_and_failures_in_denominator(self):
        r = assess(Metrics(), data(task()), k=3)
        g = r['groups'][0]
        self.assertEqual(r['counts']['graded_trials'], 4)
        self.assertEqual(r['counts']['successful_trials'], 3)
        self.assertEqual((g['pass_at_1'], g['pass_at_k'], g['pass_power_k']), (.75, 1, .25))
        self.assertEqual(r['status'], 'imported_results')

    def test_k_one_matches_single_trial_rate(self):
        g = assess(Metrics(), data(task()), k=1)['groups'][0]
        self.assertEqual((g['pass_at_1'], g['pass_at_k'], g['pass_power_k']), (.75, .75, .75))

    def test_more_repeats_required_is_unknown_not_zero(self):
        g = assess(Metrics(), data(task()), k=5)['groups'][0]
        self.assertEqual(g['pass_at_1'], .75)
        self.assertIsNone(g['pass_at_k'])
        self.assertIsNone(g['pass_power_k'])

    def test_all_fail_and_all_pass_extremes(self):
        for passed in (False, True):
            g = assess(Metrics(), data(task((passed,) * 3)))['groups'][0]
            self.assertEqual((g['pass_at_1'], g['pass_at_k'], g['pass_power_k']), (float(passed),) * 3)

    def test_macro_average_weights_tasks_equally(self):
        g = assess(Metrics(), data(task((True,) * 6), task((False,) * 3, task_id='second')))['groups'][0]
        self.assertEqual((g['pass_at_1'], g['pass_at_k'], g['pass_power_k']), (.5, .5, .5))

    def test_missing_grader_or_outcome_suppresses_cohort_instead_of_dropping_trial(self):
        for field in ('graders', 'outcome', 'transcript_ref', 'environment_reset'):
            with self.subTest(field=field):
                t = task()
                del t['trials'][0][field]
                r = assess(Metrics(), data(t, task(task_id='complete')))
                self.assertEqual(r['counts']['trials'], 8)
                self.assertEqual(r['counts']['graded_trials'], 7)
                self.assertIsNone(r['groups'][0]['pass_at_1'])

    def test_text_report_explains_interrupted_daily_trial(self):
        t = task((True,), evaluation_mode='daily')
        t['trials'][0]['status'] = 'interrupted'
        t['trials'][0]['graders'] = []
        del t['trials'][0]['outcome']
        report = assess(Metrics(), data(t))
        summary = render_summary(report)
        self.assertEqual(report['failure_reasons'], {'execution_incomplete': 1})
        self.assertIn('Execution incomplete / interrupted: 1', summary)
        self.assertIn('One acceptance run per daily task; pass@k / pass^k are not calculated', summary)
        self.assertNotIn('pass@1=Insufficient evidence', summary)

    def test_missing_entire_planned_trial_or_task_trials_cannot_inflate_scores(self):
        for trials in ([], task()['trials'][:3]):
            t = task()
            t['trials'] = trials
            r = assess(Metrics(), data(t, task(task_id='complete')))
            self.assertEqual(r['counts']['tasks'], 2)
            self.assertIsNone(r['groups'][0]['pass_at_1'])

    def test_required_graders_and_strict_boolean_types(self):
        variants = [dict(required_graders=['tests', 'security']), dict(planned_trials=True),
                    dict(reference_solution_ref=''), dict(required_graders=['tests', 'tests'])]
        for change in variants:
            t = task()
            t.update(change)
            self.assertIsNone(assess(Metrics(), data(t))['groups'][0]['pass_at_1'])
        for value in ('true', 1, None):
            t = task()
            t['trials'][0]['graders'][0]['passed'] = value
            self.assertIsNone(assess(Metrics(), data(t))['groups'][0]['pass_at_1'])

    def test_outcome_must_agree_with_all_required_graders(self):
        t = task()
        t['trials'][0]['outcome']['passed'] = False
        self.assertEqual(assess(Metrics(), data(t))['counts']['graded_trials'], 3)

    def test_model_grader_requires_human_calibration_but_not_human_every_trial(self):
        t = task()
        for trial in t['trials']:
            trial['graders'][0]['type'] = 'model'
        self.assertEqual(assess(Metrics(), data(t))['counts']['graded_trials'], 0)
        for trial in t['trials']:
            trial['graders'][0]['human_calibration_ref'] = 'PRIVATE_CALIBRATION'
        r = assess(Metrics(), data(t))
        self.assertEqual(r['counts']['graded_trials'], 4)
        self.assertEqual(r['readiness'][-1]['status'], 'missing')

    def test_duplicate_tasks_and_trials_are_idempotent(self):
        t = task()
        t['trials'].append(copy.deepcopy(t['trials'][0]))
        r = assess(Metrics(), data(t, copy.deepcopy(t)))
        self.assertEqual(r['counts']['trials'], 4)
        self.assertEqual(r['groups'][0]['pass_at_1'], .75)
        self.assertEqual(r['diagnostics'], {'duplicate_tasks': 1, 'duplicate_trials': 1})

    def test_conflicting_duplicate_fails_closed(self):
        t = task()
        alternate = copy.deepcopy(t)
        alternate['trials'][0]['outcome']['passed'] = False
        r = assess(Metrics(), data(t, alternate, task(task_id='other')))
        self.assertEqual(r['diagnostics']['conflicting_tasks'], 1)
        self.assertIsNone(r['groups'][0]['pass_at_1'])
        t['trials'].append(alternate['trials'][0])
        r = assess(Metrics(), data(t))
        self.assertEqual(r['diagnostics']['conflicting_trials'], 1)
        self.assertEqual(r['counts']['graded_trials'], 3)
        self.assertEqual(r['counts']['unknown_trials'], 1)

    def test_provider_model_and_versions_cannot_supply_each_others_repeats(self):
        tasks = [task((True,), source='claude'), task((True,), source='codex')]
        for field in ('model', 'harness_version', 'suite_version', 'suite_id'):
            t = task((True,))
            t[field] = 'different'
            tasks.append(t)
        combined = merge_metrics([Metrics('claude'), Metrics('codex')])
        r = assess(combined, data(*tasks))
        self.assertEqual(len(r['groups']), 6)
        self.assertTrue(all(g['pass_at_k'] is None for g in r['groups']))
        self.assertEqual(assess(Metrics('codex'), data(*tasks))['counts']['tasks'], 1)

    def test_legacy_effort_uses_documented_model_default_only(self):
        sol = task((True,), source='codex')
        sol['model'] = 'GPT-6-Sol'
        opus = task((True,), source='claude')
        opus['model'] = 'Opus 5.5 (1M context)'
        self.assertEqual(task_effort(sol), 'medium')
        self.assertEqual(task_effort(opus), 'medium')
        self.assertEqual(task_effort(task()), 'unknown')
        opus['reasoning_effort'] = 'high'
        self.assertEqual(task_effort(opus), 'high')
        sol['reasoning_effort'] = 'unknown'
        self.assertEqual(task_effort(sol), 'unknown')

    def test_effort_separates_groups_and_filters_legacy_records(self):
        legacy = task((True,), source='codex')
        legacy['model'] = 'gpt-6-sol'
        high = copy.deepcopy(legacy)
        high['reasoning_effort'] = 'xhigh'
        combined = data(legacy, high)
        report = assess(Metrics('codex'), combined)
        self.assertEqual(report['counts']['tasks'], 2)
        self.assertEqual(len(report['groups']), 2)
        medium = filter_evals(combined, model='GPT-6-SOL', effort='MEDIUM')
        self.assertEqual(assess(Metrics('codex'), medium)['counts']['tasks'], 1)
        self.assertEqual(assess(Metrics('codex'), filter_evals(combined, effort='xhigh'))
                         ['counts']['tasks'], 1)

    def test_time_window_cannot_turn_partial_task_into_complete_task(self):
        t = task()
        t['trials'][0]['timestamp'] = '2026-09-09T23:59:00Z'
        r = assess(Metrics(), data(t), since=parse_date('2026-09-10'), until=parse_date('2026-09-11'))
        self.assertEqual(r['counts']['trials'], 3)
        self.assertIsNone(r['groups'][0]['pass_at_k'])
        self.assertEqual(r['trial_window'], {'since': '2026-09-10', 'until': '2026-09-10'})
        self.assertEqual(assess(Metrics(), data(t), since=parse_date('2026-09-11'))['counts']['tasks'], 0)

    def test_window_keeps_tasks_with_no_trials_in_denominator(self):
        missing = task(task_id='missing')
        missing['trials'] = []
        r = assess(Metrics(), data(task(), missing), since=parse_date('2026-09-01'))
        self.assertEqual(r['counts']['tasks'], 2)
        self.assertIsNone(r['groups'][0]['pass_at_1'])

    def test_synthetic_import_is_explicitly_labelled(self):
        d = data(task())
        d['synthetic'] = True
        r = assess(Metrics(), d)
        self.assertTrue(r['synthetic'])

    def test_timestamp_requires_timezone_and_invalid_is_diagnosed(self):
        t = task()
        t['trials'][0]['timestamp'] = '2026-09-10T10:00:00'
        r = assess(Metrics(), data(t), since=parse_date('2026-09-01'))
        self.assertEqual(r['diagnostics']['invalid_timestamps'], 1)
        self.assertIsNone(r['groups'][0]['pass_at_1'])

    def test_invalid_record_does_not_vanish_into_high_score(self):
        for invalid in (None, {}, {'source': 'claude'}, {'source': 'unknown'}):
            r = assess(Metrics(), data(task(), invalid))
            self.assertEqual(r['diagnostics']['invalid_tasks'], 1)
            self.assertEqual(r['groups'][0]['pass_at_1'], .75)
            self.assertEqual(r['status'], 'partial_evidence')

    def test_report_omits_all_raw_evidence_even_in_json_download(self):
        path = self.root / 'evals.json'
        path.write_text(json.dumps(data(task())), encoding='utf-8')
        for fmt in ('json', 'txt', 'md', 'html'):
            rc, output, _ = self.cli(['--source', 'claude', '--claude-dir', str(self.root),
                                     '--eval-results', str(path), '--format', fmt])
            self.assertEqual(rc, 0)
            self.assertNotIn('PRIVATE_', output)
            self.assertIn('Anthropic', output)
            if fmt == 'html':
                payload = re.search(r'data:application/json;base64,([^\"]+)', output)[1]
                self.assertNotIn('PRIVATE_', base64.b64decode(payload).decode())

    def test_missing_logs_still_support_explicit_eval_results(self):
        path = self.root / 'evals.json'
        path.write_text(json.dumps(data(task(source='codex'))))
        rc, output, _ = self.cli(['--source', 'codex', '--codex-dir', str(self.root / 'missing'),
                                 '--eval-results', str(path), '--format', 'json'])
        self.assertEqual(rc, 0)
        r = json.loads(output)['reports']['codex']
        self.assertEqual(r['current_level'], 0)
        self.assertEqual(r['anthropic_evaluation']['groups'][0]['pass_at_1'], .75)

    def test_invalid_file_schema_and_k_have_explicit_errors(self):
        path = self.root / 'evals.json'
        for invalid in ('not json', '[]', '{"schema_version":"wrong","tasks":[]}'):
            path.write_text(invalid)
            rc, _, error = self.cli(['--eval-results', str(path), '--format', 'json'])
            self.assertEqual(rc, 2)
            self.assertNotRegex(error, r'[\u4e00-\u9fff]')
        self.assertEqual(self.cli(['--eval-k', '0', '--format', 'json'])[0], 2)
        self.assertEqual(self.cli(['--eval-results', str(self.root / 'absent'), '--format', 'json'])[0], 2)

    def test_html_methods_sources_references_and_no_external_loading(self):
        self.codex([message('user')])
        rc, output, _ = self.cli(['--claude-dir', str(self.root), '--codex-dir', str(self.root),
                                 '--format', 'html'])
        self.assertEqual(rc, 0)
        self.assertIn('id="assessment-method"', output)
        self.assertEqual(output.count('data-method-view="anthropic"'), 3)
        self.assertEqual(output.count('data-method-view="levels"'), 3)
        self.assertEqual(output.count('data-method-view="improvement"'), 3)
        self.assertIn('value="both"', output)
        self.assertIn('References · 7 items', output)
        self.assertIn('Insufficient evidence', output)
        self.assertNotIn('src="https://', output)
        self.assertNotIn('fetch(', output)
