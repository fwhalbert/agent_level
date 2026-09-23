"""Read-only project discovery and evidence checks, independent of task execution."""
import hashlib
import json

from assessment.anthropic import assess
from assessment.collection import load_project_evals
from assessment.evidence import EvidenceReader
from assessment.logs import Metrics
from tests.test_anthropic_eval import task
from tests.test_assessment_core import TempCase


class TestProjectEvidence(TempCase):
    def setUp(self):
        super().setUp()
        self.workspace = self.root / 'PRIVATE_WORKSPACE'
        self.repo = self.workspace / 'src' / 'repo'
        self.repo.mkdir(parents=True)

    def record(self, name='one', repo=None, passed=True, source='codex'):
        directory = self.workspace / f'.{source}' / 'agent-eval' / 'tasks' / name
        directory.mkdir(parents=True)

        def artifact(filename, value):
            raw = json.dumps(value).encode()
            (directory / filename).write_bytes(raw)
            return filename, hashlib.sha256(raw).hexdigest()

        definition = task((passed,), source=source, task_id=name,
                          evaluation_mode='daily', repo=str(repo or self.repo))
        trial = definition['trials'][0]
        trial['artifact_id'] = name
        trial['transcript_ref'], trial['transcript_sha256'] = artifact('trace.json', 'PRIVATE_TRANSCRIPT')
        grader = trial['graders'][0]
        grader['version'] = '1'
        grader['evidence_ref'], grader['evidence_sha256'] = artifact('grader.json', {
            'kind': 'command_result', 'grader_id': 'tests', 'grader_version': '1',
            'artifact_id': name, 'exit_code': 0 if passed else 1, 'timed_out': False, 'passed': passed,
        })
        outcome = trial['outcome']
        outcome['evidence_ref'], outcome['evidence_sha256'] = artifact('outcome.json', {
            'kind': 'task_outcome', 'artifact_id': name, 'passed': passed,
            'graders': [{'grader_id': 'tests', 'sha256': grader['evidence_sha256']}],
        })
        path = directory / 'results.json'
        path.write_text(json.dumps({'schema_version': '1.1', 'collector': 'daily-v1', 'tasks': [definition]}))
        return path

    def assessment(self, project=None):
        data, reader, counts = load_project_evals(project or self.workspace)
        return assess(Metrics('codex'), data, evidence_reader=reader), counts

    def test_existing_records_work_without_logs_in_all_report_formats(self):
        self.record()
        report, counts = self.assessment()
        self.assertEqual(counts, {'files': 1, 'tasks': 1})
        self.assertEqual(report['counts']['verified_trials'], 1)
        self.assertEqual(report['groups'][0]['daily_success_rate'], 1)
        for fmt in ('json', 'txt', 'md', 'html'):
            with self.subTest(format=fmt):
                code, output, error = self.cli([
                    '--project-dir', str(self.workspace), '--format', fmt,
                    '--claude-dir', str(self.root / 'missing-claude'),
                    '--codex-dir', str(self.root / 'missing-codex')])
                self.assertEqual(code, 0, error)
                self.assertNotIn('PRIVATE_', output)
                if fmt == 'json':
                    result = json.loads(output)['reports']['codex']
                    self.assertIsNone(result['current_level'])
                    self.assertEqual(result['anthropic_evaluation']['counts']['verified_trials'], 1)
                else:
                    self.assertIn('Anthropic', output)
                    self.assertIn('已有任务结果', output)

    def test_ancestor_discovery_filters_repo_and_uses_individual_evidence_roots(self):
        self.record()
        other = self.workspace / 'src' / 'other'
        other.mkdir()
        self.record('two', repo=other, passed=False)
        report, counts = self.assessment(self.repo)
        self.assertEqual(counts['tasks'], 1)
        self.assertEqual(report['counts']['successful_trials'], 1)
        report, counts = self.assessment()
        self.assertEqual(counts['tasks'], 2)
        self.assertEqual(report['counts']['verified_trials'], 2)
        self.assertEqual(report['counts']['failed_trials'], 1)

    def test_both_agent_directories_keep_evidence_and_source_separate(self):
        self.record(source='codex')
        self.record(source='claude', passed=False)
        data, reader, counts = load_project_evals(self.repo)
        self.assertEqual(counts, {'files': 2, 'tasks': 2})
        for source, successes, failures in (('codex', 1, 0), ('claude', 0, 1)):
            with self.subTest(source=source):
                report = assess(Metrics(source), data, evidence_reader=reader)
                self.assertEqual(report['counts']['verified_trials'], 1)
                self.assertEqual(report['counts']['successful_trials'], successes)
                self.assertEqual(report['counts']['failed_trials'], failures)

    def test_tampered_evidence_only_invalidates_affected_task(self):
        record = self.record()
        self.record('two')
        (record.parent / 'trace.json').write_text('tampered')
        report, _ = self.assessment()
        self.assertEqual(report['counts']['successful_trials'], 1)
        self.assertEqual(report['counts']['unknown_trials'], 1)
        self.assertEqual(report['diagnostics']['evidence_verification_failed'], 1)

    def test_correct_hash_cannot_hide_inconsistent_grader_or_artifact(self):
        record = self.record()
        original = json.loads(record.read_text())
        grader_path = record.parent / 'grader.json'
        payload = json.loads(grader_path.read_text())
        for change in ({'exit_code': 1}, {'artifact_id': 'wrong'}, {'grader_version': 'wrong'}):
            with self.subTest(change=change):
                grader_path.write_text(json.dumps(dict(payload, **change)))
                trial = original['tasks'][0]['trials'][0]
                trial['graders'][0]['evidence_sha256'] = hashlib.sha256(grader_path.read_bytes()).hexdigest()
                valid, reason = EvidenceReader(record.parent).verify_trial(trial)
                self.assertFalse(valid)
                self.assertEqual(reason, 'evidence_verification_failed')

    def test_symlink_and_empty_ledgers_are_rejected(self):
        record = self.record()
        content = record.read_text()
        record.write_text(json.dumps({'schema_version': '1.1', 'collector': 'daily-v1', 'tasks': []}))
        with self.assertRaises(ValueError):
            load_project_evals(self.workspace)
        target = self.root / 'copy.json'
        target.write_text(content)
        record.unlink()
        record.symlink_to(target)
        with self.assertRaises(ValueError):
            load_project_evals(self.workspace)

    def test_no_auto_evals_bypasses_existing_invalid_ledger(self):
        record = self.record()
        record.write_text('invalid JSON')
        args = ['--project-dir', str(self.workspace), '--source', 'claude',
                '--claude-dir', str(self.root), '--format', 'json']
        self.assertEqual(self.cli(args)[0], 2)
        code, output, error = self.cli(args + ['--no-auto-evals'])
        self.assertEqual(code, 0, error)
        self.assertFalse(json.loads(output)['project_task_records']['enabled'])

    def test_explicit_evidence_import_and_root_validation(self):
        record = self.record()
        args = ['--source', 'codex', '--codex-dir', str(self.root / 'missing'),
                '--eval-results', str(record), '--format', 'json']
        code, output, error = self.cli(args + ['--evidence-root', str(record.parent)])
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(output)['reports']['codex']['anthropic_evaluation']['counts']['verified_trials'], 1)
        self.assertEqual(self.cli(args + ['--evidence-root', str(self.root / 'missing')])[0], 2)
        self.assertEqual(self.cli(['--evidence-root', str(self.root), '--format', 'json'])[0], 2)
