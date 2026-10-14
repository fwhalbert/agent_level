import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch

import agent_level_record as recorder
from assessment.anthropic import assess
from assessment.collection import load_project_evals
from assessment.evidence import EvidenceReader
from assessment.logs import Metrics
from tests.test_assessment_core import TempCase


class TestDailyRecorder(TempCase):
    def setUp(self):
        super().setUp()
        self.workspace = self.root / 'workspace'
        self.repo = self.workspace / 'src' / 'repo'
        self.repo.mkdir(parents=True)

    def invoke(self, args):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = recorder.main(args)
        return code, output.getvalue().strip(), error.getvalue()

    def start(self, command=None, source='codex', timeout=10, model='test-model', effort=None):
        args = ['start', '--repo', str(self.repo), '--workspace', str(self.workspace),
                '--source', source, '--model', model, '--criteria', 'Run the specified check',
                '--timeout', str(timeout)]
        if effort is not None:
            args += ['--reasoning-effort', effort]
        if command is not None:
            args += ['--'] + command
        code, output, error = self.invoke(args)
        self.assertEqual(code, 0, error)
        return Path(output)

    def finish(self, directory, *extra):
        return self.invoke(['finish', '--task-dir', str(directory), *extra])

    def assessment(self, project=None, source='codex'):
        data, reader, counts = load_project_evals(project or self.workspace)
        return assess(Metrics(source), data, evidence_reader=reader), counts

    def test_success_failure_and_nested_repo_discovery(self):
        for source, exit_code in (('codex', 0), ('claude', 7)):
            with self.subTest(source=source):
                directory = self.start([sys.executable, '-c',
                                        'from pathlib import Path; import sys; '
                                        'print(Path.cwd()); sys.exit(sys.argv[1] == "7")', str(exit_code)], source)
                self.assertEqual(directory.parent, self.workspace / f'.{source}/agent_level/tasks')
                code, _, error = self.finish(directory)
                self.assertEqual(code, 0 if exit_code == 0 else 1, error)
                report, _ = self.assessment(self.repo, source)
                self.assertEqual(report['counts']['verified_trials'], 1)
                self.assertEqual(report['counts']['successful_trials'], int(exit_code == 0))
                self.assertEqual(report['counts']['failed_trials'], int(exit_code != 0))
                self.assertIn(str(self.repo), (directory / 'check.log').read_text())
                self.assertIsNone(report['groups'][0]['pass_at_k'])
        _, counts = self.assessment()
        self.assertEqual(counts, {'files': 2, 'tasks': 2})

    def test_model_and_effort_are_separate_recorded_conditions(self):
        directory = self.start([sys.executable, '-c', 'print("checked")'],
                               model='GPT-6-Sol', effort='xhigh')
        task = json.loads((directory / 'results.json').read_text())['tasks'][0]
        self.assertEqual((task['model'], task['reasoning_effort']), ('GPT-6-Sol', 'xhigh'))
        self.assertEqual(self.finish(directory)[0], 0)
        task = json.loads((directory / 'results.json').read_text())['tasks'][0]
        self.assertEqual((task['model'], task['reasoning_effort']), ('GPT-6-Sol', 'xhigh'))
        legacy_default = self.start(model='unidentified-model')
        self.assertEqual(json.loads((legacy_default / 'results.json').read_text())['tasks'][0]
                         ['reasoning_effort'], 'unknown')

    def test_registered_and_unverifiable_work_stays_unknown(self):
        directory = self.start()
        report, _ = self.assessment()
        self.assertEqual(report['counts']['unknown_trials'], 1)
        self.assertEqual(report['failure_reasons'], {'execution_incomplete': 1})
        self.assertEqual(self.finish(directory)[0], 2)
        self.assertEqual(self.finish(directory, '--unknown', 'hardware unavailable')[0], 2)
        report, _ = self.assessment()
        self.assertEqual(report['counts']['unknown_trials'], 1)
        self.assertEqual(report['counts']['successful_trials'], 0)
        self.assertIn('hardware unavailable', (directory / 'journal.json').read_text())

    def test_not_yet_written_trace_is_incomplete_but_missing_finished_trace_is_missing(self):
        directory = self.start()
        path = directory / 'results.json'
        ledger = json.loads(path.read_text())
        for status, reason in (('running', 'execution_incomplete'), ('grading', 'execution_incomplete'),
                               ('error', 'evidence_missing')):
            ledger['tasks'][0]['trials'][0]['status'] = status
            path.write_text(json.dumps(ledger))
            report, _ = self.assessment()
            self.assertEqual(report['failure_reasons'], {reason: 1})

    def test_timeout_and_launch_failure_do_not_become_pass_or_failure(self):
        for command, timeout in (([sys.executable, '-c', 'import time; time.sleep(30)'], .05),
                                 ([str(self.root / 'missing-command')], 10)):
            with self.subTest(command=command):
                directory = self.start(command, timeout=timeout)
                self.assertEqual(self.finish(directory)[0], 2)
                ledger = json.loads((directory / 'results.json').read_text())
                self.assertEqual(ledger['tasks'][0]['trials'][0]['status'], 'error')
                self.assertNotIn('outcome', ledger['tasks'][0]['trials'][0])
        report, _ = self.assessment()
        self.assertEqual(report['counts']['unknown_trials'], 2)
        self.assertEqual(report['counts']['failed_trials'], 0)

    def test_completed_results_cannot_be_overwritten_or_rerun(self):
        directory = self.start([sys.executable, '-c', 'print("one run")'])
        self.assertEqual(self.finish(directory)[0], 0)
        original = (directory / 'results.json').read_bytes()
        self.assertEqual(self.finish(directory)[0], 2)
        self.assertEqual(self.finish(directory, '--unknown', 'replace')[0], 2)
        self.assertEqual((directory / 'results.json').read_bytes(), original)

    def test_tampered_evidence_is_rejected_by_existing_reader(self):
        directory = self.start([sys.executable, '-c', 'print("checked")'])
        self.assertEqual(self.finish(directory)[0], 0)
        (directory / 'grader.json').write_text('{}')
        report, _ = self.assessment()
        self.assertEqual(report['counts']['verified_trials'], 0)
        self.assertEqual(report['counts']['unknown_trials'], 1)

    def test_interrupted_grading_can_only_be_closed_as_unknown(self):
        directory = self.start([sys.executable, '-c', 'raise Exception("must not run")'])
        path = directory / 'results.json'
        ledger = json.loads(path.read_text())
        ledger['tasks'][0]['trials'][0]['status'] = 'grading'
        path.write_text(json.dumps(ledger))
        self.assertEqual(self.finish(directory)[0], 2)
        self.assertEqual(self.finish(directory, '--unknown', 'previous process interrupted')[0], 2)
        self.assertFalse((directory / 'check.log').exists())
        self.assertEqual(self.assessment()[0]['counts']['unknown_trials'], 1)
        self.assertEqual(self.assessment()[0]['failure_reasons'], {'interruption': 1})
        self.assertEqual(json.loads((directory / 'journal.json').read_text())['failure_reason'],
                         'interruption')

    def test_explicit_unknown_reason_overrides_interrupted_grading_default(self):
        directory = self.start([sys.executable, '-c', 'raise Exception("must not run")'])
        path = directory / 'results.json'
        ledger = json.loads(path.read_text())
        ledger['tasks'][0]['trials'][0]['status'] = 'grading'
        path.write_text(json.dumps(ledger))
        self.assertEqual(self.finish(directory, '--unknown', 'verification device lost',
                                     '--reason', 'verification_unavailable')[0], 2)
        self.assertEqual(self.assessment()[0]['failure_reasons'], {'verification_unavailable': 1})
        self.assertFalse((directory / 'check.log').exists())

    def test_tampered_or_missing_output_is_unknown(self):
        directory = self.start([sys.executable, '-c', 'print("checked")'])
        self.assertEqual(self.finish(directory)[0], 0)
        output = directory / 'check.log'
        output.write_text('changed output')
        for missing in (False, True):
            with self.subTest(missing=missing):
                if missing:
                    output.unlink()
                report, _ = self.assessment()
                self.assertEqual(report['counts']['verified_trials'], 0)
                self.assertEqual(report['counts']['successful_trials'], 0)
                self.assertEqual(report['counts']['unknown_trials'], 1)

    def test_rehashed_journal_must_match_grader_and_artifact(self):
        directory = self.start([sys.executable, '-c', 'print("checked")'])
        self.assertEqual(self.finish(directory)[0], 0)
        journal_path = directory / 'journal.json'
        original = json.loads(journal_path.read_text())
        ledger_path = directory / 'results.json'
        ledger = json.loads(ledger_path.read_text())
        for change in ({'exit_code': 1}, {'exit_code': False}, {'task_id': 'different'},
                       {'timed_out': True}, {'error': 'interrupted'}, {'output_ref': '../outside'}):
            with self.subTest(change=change):
                journal_path.write_text(json.dumps(dict(original, **change)))
                ledger['tasks'][0]['trials'][0]['transcript_sha256'] = hashlib.sha256(journal_path.read_bytes()).hexdigest()
                ledger_path.write_text(json.dumps(ledger))
                report, _ = self.assessment()
                self.assertEqual(report['counts']['verified_trials'], 0)
                self.assertEqual(report['counts']['unknown_trials'], 1)

    def test_output_limit_stops_command_and_bounds_file(self):
        limit = 8192
        directory = self.start([sys.executable, '-c',
                                'import os, time; '
                                'os.write(1, b"x" * 65536); time.sleep(30)'], timeout=3)
        with patch.object(recorder, 'MAX_EVIDENCE_BYTES', limit):
            code, result, _ = self.finish(directory)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(result)['error'], 'acceptance output exceeds evidence size limit')
        self.assertEqual((directory / 'check.log').stat().st_size, limit)
        self.assertEqual(self.assessment()[0]['counts']['unknown_trials'], 1)

    def test_exact_output_limit_and_closed_stdout_are_supported(self):
        directory = self.start([sys.executable, '-c',
                                'import os; os.write(1, b"x" * 8192); os.close(1); os.close(2)'])
        with patch.object(recorder, 'MAX_EVIDENCE_BYTES', 8192):
            self.assertEqual(self.finish(directory)[0], 0)
        self.assertEqual(self.assessment()[0]['counts']['verified_trials'], 1)

    def test_closed_stdout_does_not_bypass_timeout(self):
        directory = self.start([sys.executable, '-c',
                                'import os, time; os.close(1); os.close(2); time.sleep(30)'], timeout=.1)
        code, result, _ = self.finish(directory)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(result)['error'], 'acceptance timed out')

    def test_descendant_holding_stdout_does_not_bypass_timeout(self):
        directory = self.start([sys.executable, '-c',
                                'import os, time; '
                                'pid = os.fork(); '
                                'time.sleep(30) if pid == 0 else None'], timeout=.1)
        code, result, _ = self.finish(directory)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(result)['error'], 'acceptance timed out')

    def test_record_store_cannot_be_a_symlink(self):
        (self.workspace / '.codex').symlink_to(self.root, target_is_directory=True)
        code, _, error = self.invoke(['start', '--repo', str(self.repo), '--workspace', str(self.workspace),
                                     '--source', 'codex', '--model', 'test', '--criteria', 'test'])
        self.assertEqual(code, 2)
        self.assertIn('symlinks', error)

    def test_simultaneous_finish_does_not_execute_check(self):
        directory = self.start([sys.executable, '-c', 'print("checked")'])
        with (directory / '.lock').open('a') as lock:
            recorder.fcntl.flock(lock, recorder.fcntl.LOCK_EX)
            self.assertEqual(self.finish(directory)[0], 2)
            self.assertFalse((directory / 'check.log').exists())
        self.assertEqual(self.finish(directory)[0], 0)

    def test_invalid_timeout_and_workspace_are_rejected_before_creation(self):
        base = ['start', '--repo', str(self.repo), '--source', 'codex', '--model', 'test', '--criteria', 'test']
        for value in ('nan', 'inf', '-1', '0'):
            self.assertEqual(self.invoke(base + ['--timeout', value])[0], 2)
        self.assertEqual(self.invoke(base + ['--reasoning-effort', ' '])[0], 2)
        other = self.root / 'other'
        other.mkdir()
        self.assertEqual(self.invoke(base + ['--workspace', str(other)])[0], 2)
        self.assertFalse((self.repo / '.codex').exists())

    def test_keyboard_interrupt_preserves_unknown_evidence(self):
        directory = self.start([sys.executable, '-c', 'import time; time.sleep(30)'])
        original = recorder.selectors.DefaultSelector.select
        calls = []

        def interrupted(selector, *args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise KeyboardInterrupt
            return original(selector, *args, **kwargs)

        with patch.object(recorder.selectors.DefaultSelector, 'select', interrupted):
            self.assertEqual(self.finish(directory)[0], 2)
        self.assertEqual(self.assessment()[0]['counts']['unknown_trials'], 1)

    def test_frozen_acceptance_cannot_change_before_execution(self):
        changes = ({'acceptance_criteria': 'changed'}, {'check_command': [sys.executable, '-c', 'pass']},
                   {'check_timeout_seconds': 99}, {'required_graders': ['different']},
                   {'planned_trials': 2}, {'model': 'different'}, {'acceptance_standard': {}},
                   {'acceptance_registration': None})
        for change in changes:
            with self.subTest(change=change):
                directory = self.start([sys.executable, '-c', 'print("checked")'])
                path = directory / 'results.json'
                ledger = json.loads(path.read_text())
                ledger['tasks'][0].update(change)
                path.write_text(json.dumps(ledger))
                self.assertEqual(self.finish(directory)[0], 2)
                self.assertFalse((directory / 'check.log').exists())
                report, _ = self.assessment()
                self.assertEqual(report['counts']['successful_trials'], 0)
                self.assertIn('acceptance_registration_invalid', report['failure_reasons'])

    def test_explicit_standard_and_session_provenance_remain_private(self):
        args = ['start', '--repo', str(self.repo), '--workspace', str(self.workspace),
                '--source', 'codex', '--model', 'PRIVATE_MODEL', '--criteria', 'PRIVATE_CRITERIA',
                '--criteria-version', 'PRIVATE_VERSION', '--criteria-author', 'PRIVATE_AUTHOR',
                '--criteria-review-source', 'independent_model', '--criteria-reviewer', 'PRIVATE_REVIEWER',
                '--criteria-review-ref', 'PRIVATE_REVIEW', '--session-id', 'PRIVATE_SESSION',
                '--', sys.executable, '-c', 'print("checked")']
        code, output, error = self.invoke(args)
        self.assertEqual(code, 0, error)
        directory = Path(output)
        self.assertEqual(self.finish(directory)[0], 0)
        report, _ = self.assessment()
        self.assertEqual(report['counts']['session_linked_trials'], 1)
        self.assertEqual(report['acceptance_standard_coverage']['reviewed'], 1)
        self.assertEqual(report['acceptance_standard_coverage']['frozen'], 1)
        self.assertNotIn('PRIVATE_', json.dumps(report))
        code, located, error = self.invoke(['locate', '--workspace', str(self.workspace),
                                           '--task-ref', report['task_diagnostics'][0]['task_ref']])
        self.assertEqual(code, 0, error)
        self.assertEqual(located, str(directory))

    def test_trial_registration_link_cannot_be_removed_or_replaced(self):
        directory = self.start([sys.executable, '-c', 'pass'])
        path = directory / 'results.json'
        original = json.loads(path.read_text())
        for replacement in (None, {'evidence_ref': '../outside', 'evidence_sha256': '0' * 64}):
            ledger = json.loads(json.dumps(original))
            ledger['tasks'][0]['trials'][0]['acceptance_registration'] = replacement
            path.write_text(json.dumps(ledger))
            self.assertEqual(self.finish(directory)[0], 2)
            self.assertFalse((directory / 'check.log').exists())
            self.assertEqual(self.assessment()[0]['failure_reasons'], {'acceptance_registration_invalid': 1})
        path.write_text(json.dumps(original))
        self.assertEqual(self.finish(directory)[0], 0)
        ledger = json.loads(path.read_text())
        del ledger['tasks'][0]['trials'][0]['acceptance_registration']
        path.write_text(json.dumps(ledger))
        report, _ = self.assessment()
        self.assertEqual(report['counts']['successful_trials'], 0)
        self.assertEqual(report['failure_reasons'], {'acceptance_registration_invalid': 1})

    def human_review(self, directory, **extra):
        review = dict(type='human', reviewer='PRIVATE_HUMAN', reviewed_at='2026-09-30T10:00:00Z',
                      result='overturned', selection='all_failure', failure_category='tests',
                      human_interventions=2,
                      interventions=[dict(type='correction', count=1, minutes=4), dict(type='clarification', count=1)])
        review.update(extra)
        path = self.root / 'review.json'
        path.write_text(json.dumps(review))
        return self.invoke(['review', '--task-dir', str(directory), '--review-file', str(path)])

    def test_review_preserves_verdict_and_tracks_missing_interventions(self):
        directory = self.start([sys.executable, '-c', 'raise SystemExit(1)'])
        self.assertEqual(self.finish(directory)[0], 1)
        artifacts = {name: (directory / name).read_bytes()
                     for name in ('registration.json', 'journal.json', 'grader.json', 'outcome.json', 'check.log')}
        self.assertEqual(self.human_review(directory)[0], 0)
        for name, raw in artifacts.items():
            self.assertEqual((directory / name).read_bytes(), raw)
        report, _ = self.assessment()
        self.assertEqual(report['counts']['failed_trials'], 1)
        self.assertEqual(report['review_summary']['reviewed_failure_trials'], 1)
        self.assertEqual(report['review_summary']['failure_categories'], {'tests': 1})
        self.assertEqual(report['groups'][0]['human_interventions']['total'], 2)
        self.assertNotIn('PRIVATE_', json.dumps(report))
        # A later review may declare the intervention count unavailable; it remains unknown.
        self.assertEqual(self.human_review(directory, reviewed_at='2026-09-30T11:00:00Z',
                                          human_interventions=None, interventions=[])[0], 0)
        report, _ = self.assessment()
        self.assertIsNone(report['groups'][0]['human_interventions']['total'])
        self.assertEqual(report['groups'][0]['human_interventions']['missing'], 1)
        task = json.loads((directory / 'results.json').read_text())['tasks'][0]
        self.assertEqual(len(task['trials'][0]['human_reviews']), 2)

    def test_invalid_and_tampered_reviews_do_not_become_human_evidence(self):
        directory = self.start([sys.executable, '-c', 'print("checked")'])
        self.assertEqual(self.human_review(directory)[0], 2)  # running task
        self.assertEqual(self.finish(directory)[0], 0)
        for change in ({'type': 'agent'}, {'human_interventions': -1}, {'human_interventions': True},
                       {'human_interventions': 1.5}, {'reviewer': ''}, {'result': 'passed'},
                       {'reviewed_at': '2026-09-30T10:00:00'},
                       {'interventions': [dict(type='correction', count=99)]},
                       {'interventions': [dict(type='correction', count=2, minutes=float('nan'))]},
                       {'evidence_ref': '../outside'}):
            with self.subTest(change=change):
                self.assertEqual(self.human_review(directory, **change)[0], 2)
        self.assertEqual(self.human_review(directory)[0], 0)
        path = directory / 'results.json'
        ledger = json.loads(path.read_text())
        ledger['tasks'][0]['trials'][0]['human_reviews'][0]['evidence_ref'] = '../outside'
        path.write_text(json.dumps(ledger))
        report, _ = self.assessment()
        self.assertEqual(report['review_summary']['reviewed_success_trials'], 0)
        self.assertEqual(report['diagnostics']['invalid_human_reviews'], 1)
        self.assertEqual(report['counts']['successful_trials'], 1)

    def test_unknown_reason_taxonomy_and_legacy_journal_diagnosis(self):
        cases = (([sys.executable, '-c', 'import time; time.sleep(30)'], .03, 'timeout'),
                 ([str(self.root / 'missing')], 10, 'launch_failure'),
                 ([sys.executable, '-c', 'import os, signal; os.kill(os.getpid(), signal.SIGTERM)'], 10, 'interruption'))
        for command, timeout, reason in cases:
            with self.subTest(reason=reason):
                directory = self.start(command, timeout=timeout)
                self.assertEqual(self.finish(directory)[0], 2)
                path = directory / 'results.json'
                ledger = json.loads(path.read_text())
                self.assertEqual(ledger['tasks'][0]['trials'][0]['failure_reason'], reason)
                self.assertIn(reason, self.assessment()[0]['failure_reasons'])
                if reason == 'timeout':
                    del ledger['tasks'][0]['trials'][0]['failure_reason']
                    path.write_text(json.dumps(ledger))
                    self.assertIn('timeout', self.assessment()[0]['failure_reasons'])
        directory = self.start()
        self.assertEqual(self.finish(directory, '--unknown', 'device unavailable', '--reason', 'verification_unavailable')[0], 2)
        self.assertIn('verification_unavailable', self.assessment()[0]['failure_reasons'])

    def test_unknown_reason_comes_from_hash_checked_journal(self):
        directory = self.start()
        self.assertEqual(self.finish(directory, '--unknown', 'acceptance interrupted',
                                     '--reason', 'interruption')[0], 2)
        path = directory / 'results.json'
        ledger = json.loads(path.read_text())
        ledger['tasks'][0]['trials'][0]['failure_reason'] = 'verification_unavailable'
        path.write_text(json.dumps(ledger))
        self.assertEqual(self.assessment()[0]['failure_reasons'], {'interruption': 1})
        journal_path = directory / 'journal.json'
        journal = json.loads(journal_path.read_text())
        journal['failure_reason'] = 'verification_unavailable'
        journal_path.write_text(json.dumps(journal))
        self.assertEqual(self.assessment()[0]['failure_reasons'], {'evidence_verification_failed': 1})
        self.assertEqual(self.assessment()[0]['counts']['unknown_trials'], 1)

    def test_seeded_review_plan_is_read_only_and_not_a_review(self):
        for _ in range(6):
            self.assertEqual(self.finish(self.start([sys.executable, '-c', 'pass']))[0], 0)
        self.assertEqual(self.finish(self.start([sys.executable, '-c', 'raise SystemExit(1)']))[0], 1)
        unknown = self.start()
        self.assertEqual(self.finish(unknown, '--unknown', 'unavailable')[0], 2)
        args = ['review-plan', '--workspace', str(self.workspace), '--seed', '42']
        before = {path: path.read_bytes() for path in self.workspace.rglob('results.json')}
        code, output, error = self.invoke(args)
        self.assertEqual(code, 0, error)
        self.assertEqual(self.invoke(args)[1], output)
        plan = json.loads(output)
        self.assertEqual(len(plan['selected']), 4)
        self.assertFalse(plan['reviewed'])
        self.assertEqual(sum(item['selection'] == 'random_success' for item in plan['selected']), 2)
        self.assertEqual(before, {path: path.read_bytes() for path in self.workspace.rglob('results.json')})

    def test_review_plan_stratifies_models_and_explicit_imports_check_reviews(self):
        directories = [self.start([sys.executable, '-c', 'pass'], model=model)
                       for model in ('model-a', 'model-b')]
        for directory in directories:
            self.assertEqual(self.finish(directory)[0], 0)
        self.assertEqual(self.human_review(directories[0], selection='random_success', result='confirmed')[0], 0)
        ledger = json.loads((directories[0] / 'results.json').read_text())
        report = assess(Metrics('codex'), ledger, evidence_reader=EvidenceReader(directories[0]))
        self.assertEqual(report['review_summary']['reviewed_success_trials'], 1)
        self.assertEqual(report['counts']['verified_trials'], 1)
        code, output, error = self.invoke(['review-plan', '--workspace', str(self.workspace), '--seed', '42'])
        self.assertEqual(code, 0, error)
        plan = json.loads(output)
        self.assertEqual(plan['sample_scope'], 'per_group')
        self.assertEqual(len(plan['success_sample_groups']), 2)
        self.assertEqual(len(plan['selected']), 2)  # Each small group rounds upward.
        self.assertTrue(all(item['sampled'] == 1 for item in plan['success_sample_groups']))
