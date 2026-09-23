"""Meaningful before/after comparisons must fail closed on missing evidence."""
import copy
import hashlib
import json

from assessment.evidence import EvidenceReader
from assessment.improvement import assess, _spec_digest
from tests.test_assessment_core import TempCase


class TestImprovement(TempCase):
    def put(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = content if isinstance(content, bytes) else json.dumps(content).encode()
        path.write_bytes(raw)
        return name, hashlib.sha256(raw).hexdigest()

    def fixture(self, task_count=5, regress_last=False):
        base = {'source': 'codex', 'suite_id': 'PRIVATE_SUITE', 'suite_version': '1',
                'model': 'PRIVATE_MODEL', 'baseline_harness_version': 'v1',
                'candidate_harness_version': 'v2', 'change_kind': 'workflow'}
        ids = [f'PRIVATE_TASK_{i}' for i in range(task_count)]
        comp = dict(base)
        tasks = []
        for version, passed in (('v1', False), ('v2', True)):
            for tid in ids:
                actual_passed = (not passed) if regress_last and tid == ids[-1] else passed
                trials = []
                for index in range(3):
                    artifact = f'{version}-{tid}-{index}'
                    transcript_ref, transcript_sha256 = self.put(artifact + '/trace.json',
                                                                ('PRIVATE_TRACE_' + artifact).encode())
                    grader_result = {'kind': 'command_result', 'task_id': tid, 'grader_id': 'tests',
                                     'grader_version': '1', 'artifact_id': artifact,
                                     'exit_code': 0 if actual_passed else 1,
                                     'timed_out': False, 'passed': actual_passed}
                    grader_ref, grader_sha256 = self.put(artifact + '/grader.json', grader_result)
                    outcome_result = {'kind': 'task_outcome', 'task_id': tid, 'artifact_id': artifact,
                                      'passed': actual_passed,
                                      'graders': [{'grader_id': 'tests', 'sha256': grader_sha256}]}
                    outcome_ref, outcome_sha256 = self.put(artifact + '/outcome.json', outcome_result)
                    trials.append({'trial_id': f'{artifact}-trial', 'task_id': tid, 'status': 'completed',
                                   'timestamp': '2026-09-10T10:00:00Z', 'environment_reset': True,
                                   'transcript_kind': 'session_export', 'transcript_ref': transcript_ref,
                                   'transcript_sha256': transcript_sha256, 'artifact_id': artifact,
                                   'human_interventions': 0,
                                   'graders': [{'grader_id': 'tests', 'type': 'code', 'version': '1',
                                                'passed': actual_passed, 'evidence_ref': grader_ref,
                                                'evidence_sha256': grader_sha256}],
                                   'outcome': {'passed': actual_passed, 'evidence_ref': outcome_ref,
                                               'evidence_sha256': outcome_sha256}})
                tasks.append({'source': 'codex', 'suite_id': base['suite_id'],
                              'suite_version': base['suite_version'], 'model': base['model'],
                              'harness_version': version, 'task_id': tid,
                              'acceptance_criteria': 'PRIVATE_FIXED_CHECK',
                              'reference_solution_ref': 'PRIVATE_REFERENCE',
                              'required_graders': ['tests'], 'planned_trials': 3,
                              'evaluation_mode': 'controlled', 'trials': trials})
        plan = dict(kind='improvement_plan', task_ids=ids, planned_trials_per_task=3,
                    registered_at='2026-09-09T10:00:00Z',
                    task_specs_sha256=_spec_digest(tasks[:task_count]),
                    grader_versions={tid: {'tests': '1'} for tid in ids}, **base)
        for name, content in (('plan', plan), ('feedback', b'PRIVATE_FAILURE_ANALYSIS'),
                              ('change', b'PRIVATE_VERSION_DIFF'), ('rollback', b'PRIVATE_ROLLBACK')):
            comp[name + '_ref'], comp[name + '_sha256'] = self.put(name + '.json', content)
        return {'schema_version': '1.1', 'tasks': tasks,
                'improvement_comparisons': [comp]}

    def run_eval(self, data, checked=True):
        return assess(data, EvidenceReader(self.root) if checked else None)['comparisons'][0]

    def test_checked_gain_reports_effect_without_claiming_independent_execution(self):
        data = self.fixture()
        report = assess(data, EvidenceReader(self.root))
        row = report['comparisons'][0]
        self.assertEqual(row['status'], 'supported_gain')
        self.assertEqual((row['baseline_autonomous'], row['candidate_autonomous']), (0, 1))
        self.assertEqual((row['tasks'], row['trials_per_variant']), (5, 15))
        self.assertEqual(row['sign_test_p'], 1 / 32)
        self.assertFalse(report['independent_execution_verified'])

    def test_no_local_evidence_is_not_proof(self):
        self.assertEqual(self.run_eval(self.fixture(), checked=False)['reason'], 'local_evidence_required')

    def test_missing_trial_or_changed_rubric_blocks_comparison(self):
        for change in ('missing_trial', 'rubric_change', 'missing_interventions', 'journal_only'):
            with self.subTest(change=change):
                data = self.fixture()
                candidate = data['tasks'][5]
                if change == 'missing_trial':
                    candidate['trials'].pop()
                elif change == 'rubric_change':
                    candidate['acceptance_criteria'] = 'PRIVATE_EASIER_CHECK'
                elif change == 'missing_interventions':
                    del candidate['trials'][0]['human_interventions']
                else:
                    candidate['trials'][0]['transcript_kind'] = 'collector_journal'
                self.assertEqual(self.run_eval(data)['reason'], 'incomplete_or_incomparable_trials')

    def test_tampered_file_or_selected_tasks_cannot_show_gain(self):
        data = self.fixture()
        (self.root / data['improvement_comparisons'][0]['change_ref']).write_bytes(b'tampered')
        self.assertEqual(self.run_eval(data)['reason'], 'comparison_artifact_failed')
        data = self.fixture()
        data['tasks'].pop()
        self.assertEqual(self.run_eval(data)['reason'], 'task_set_mismatch')

    def test_reused_trial_evidence_cannot_count_as_independent_runs(self):
        data = self.fixture()
        trials = data['tasks'][0]['trials']
        trials[1]['artifact_id'] = trials[0]['artifact_id']
        trials[1]['transcript_ref'] = trials[0]['transcript_ref']
        trials[1]['transcript_sha256'] = trials[0]['transcript_sha256']
        trials[1]['graders'] = copy.deepcopy(trials[0]['graders'])
        trials[1]['outcome'] = copy.deepcopy(trials[0]['outcome'])
        self.assertEqual(self.run_eval(data)['reason'], 'incomplete_or_incomparable_trials')

    def test_regressions_not_supported(self):
        row = self.run_eval(self.fixture(regress_last=True))
        self.assertEqual(row['status'], 'gain_with_regressions')
        self.assertEqual(row['regressed_tasks'], 1)

    def test_synthetic_data_and_cli_do_not_expose_evidence(self):
        data = self.fixture()
        synthetic = copy.deepcopy(data)
        synthetic['synthetic'] = True
        self.assertEqual(self.run_eval(synthetic)['reason'], 'synthetic_data')
        source = self.root / 'evals.json'
        source.write_text(json.dumps(data), encoding='utf-8')
        rc, output, _ = self.cli(['--source', 'codex', '--codex-dir', str(self.root / 'missing'),
                                  '--eval-results', str(source), '--evidence-root', str(self.root),
                                  '--format', 'json'])
        self.assertEqual(rc, 0)
        report = json.loads(output)['reports']['codex']['self_improvement_evaluation']
        self.assertEqual(report['comparisons'][0]['status'], 'supported_gain')
        self.assertNotIn('PRIVATE_', output)
        rc, html, _ = self.cli(['--source', 'codex', '--codex-dir', str(self.root / 'missing'),
                                '--eval-results', str(source), '--evidence-root', str(self.root),
                                '--format', 'html'])
        self.assertEqual(rc, 0)
        self.assertIn('data-method-view="improvement"', html)
        self.assertNotIn('PRIVATE_', html)

    def test_other_source_comparison_is_not_invalid_for_selected_source(self):
        report = assess(self.fixture(), EvidenceReader(self.root), sources={'claude'})
        self.assertEqual(report['comparisons'], [])
        self.assertEqual(report['diagnostics'], {})
