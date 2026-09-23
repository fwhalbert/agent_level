import contextlib
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch

import agent_level_record as recorder
from assessment.anthropic import assess
from assessment.collection import load_project_evals
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

    def start(self, command=None, source='codex', timeout=10):
        args = ['start', '--repo', str(self.repo), '--workspace', str(self.workspace),
                '--source', source, '--model', 'test-model', '--criteria', 'Run the specified check',
                '--timeout', str(timeout)]
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

    def test_registered_and_unverifiable_work_stays_unknown(self):
        directory = self.start()
        report, _ = self.assessment()
        self.assertEqual(report['counts']['unknown_trials'], 1)
        self.assertEqual(self.finish(directory)[0], 2)
        self.assertEqual(self.finish(directory, '--unknown', 'hardware unavailable')[0], 2)
        report, _ = self.assessment()
        self.assertEqual(report['counts']['unknown_trials'], 1)
        self.assertEqual(report['counts']['successful_trials'], 0)
        self.assertIn('hardware unavailable', (directory / 'journal.json').read_text())

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
        other = self.root / 'other'
        other.mkdir()
        self.assertEqual(self.invoke(base + ['--workspace', str(other)])[0], 2)
        self.assertFalse((self.repo / '.codex').exists())

    def test_keyboard_interrupt_preserves_unknown_evidence(self):
        directory = self.start([sys.executable, '-c', 'import time; time.sleep(30)'])
        original = recorder.subprocess.Popen.wait
        calls = []

        def interrupted(process, *args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise KeyboardInterrupt
            return original(process, *args, **kwargs)

        with patch.object(recorder.subprocess.Popen, 'wait', interrupted):
            self.assertEqual(self.finish(directory)[0], 2)
        self.assertEqual(self.assessment()[0]['counts']['unknown_trials'], 1)
