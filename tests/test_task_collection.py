"""Local evidence verification and partial-result statistics."""
import copy
import hashlib

from assessment.anthropic import assess
from assessment.evidence import EvidenceReader, junit_result
from assessment.logs import Metrics, parse_date
from tests.test_anthropic_eval import task, data
from tests.test_assessment_core import TempCase


class TestPartialResults(TempCase):
    def test_unknown_and_unexecuted_are_both_in_bounds(self):
        t = task((True, False, True))
        t['planned_trials'] = 4
        del t['trials'][2]['outcome']
        r = assess(Metrics(), data(t))
        c, g = r['counts'], r['groups'][0]
        self.assertEqual((c['successful_trials'], c['failed_trials'], c['unknown_trials'], c['not_run_trials']), (1, 1, 1, 1))
        self.assertEqual(g['coverage'], .5)
        self.assertEqual(g['observed_success_rate'], .5)
        self.assertEqual(g['success_bounds'], [.25, .75])
        self.assertIsNone(g['pass_at_1'])

    def test_one_bad_cohort_does_not_erase_another(self):
        bad = task(task_id='bad')
        bad['model'] = 'different-model'
        bad['trials'][0]['timestamp'] = 'bad'
        r = assess(Metrics(), data(task(), bad))
        self.assertEqual(sum(g['pass_at_1'] is not None for g in r['groups']), 1)
        self.assertEqual(r['counts']['graded_trials'], 7)

    def test_conflicting_trial_only_quarantines_that_trial(self):
        t = task((True, False))
        duplicate = copy.deepcopy(t['trials'][0]); duplicate['outcome']['passed'] = False
        t['trials'].append(duplicate)
        r = assess(Metrics(), data(t))
        self.assertEqual(r['counts']['failed_trials'], 1)
        self.assertEqual(r['counts']['unknown_trials'], 1)
        self.assertEqual(r['groups'][0]['success_bounds'], [0, .5])

    def test_daily_does_not_require_reset_or_reference_or_compute_repeat_scores(self):
        t = task((True,), evaluation_mode='daily')
        del t['reference_solution_ref']; del t['trials'][0]['environment_reset']
        g = assess(Metrics(), data(t), k=1)['groups'][0]
        self.assertEqual(g['daily_success_rate'], 1)
        self.assertIsNone(g['pass_at_1'])
        self.assertIsNone(g['pass_at_k'])
        self.assertLess(g['daily_wilson_95'][0], .3)
        self.assertAlmostEqual(g['daily_wilson_95'][1], 1)

    def test_modes_do_not_mix_and_daily_plan_is_one(self):
        d = task((True,), evaluation_mode='daily')
        r = assess(Metrics(), data(d, task((True,))))
        self.assertEqual(len(r['groups']), 2)
        d['planned_trials'] = 2
        self.assertIsNone(assess(Metrics(), data(d))['groups'][0]['daily_success_rate'])

    def test_window_counts_outside_as_unknown_not_unexecuted(self):
        t = task((True, False))
        t['trials'][0]['timestamp'] = '2026-09-09T10:00:00Z'
        r = assess(Metrics(), data(t), since=parse_date('2026-09-10'))
        c = r['counts']
        self.assertEqual((c['trials'], c['expected_trials'], c['unknown_trials'], c['not_run_trials'], c['outside_window_trials']), (1, 2, 1, 0, 1))
        self.assertEqual(r['groups'][0]['success_bounds'], [0, .5])


class TestEvidence(TempCase):
    def test_junit_actual_cases_and_aggregate_only(self):
        self.assertTrue(junit_result(b'<testsuite><testcase name="a"/></testsuite>'))
        self.assertFalse(junit_result(b'<testsuite><testcase><failure/></testcase></testsuite>'))
        self.assertFalse(junit_result(b'<testsuites><testsuite tests="3" errors="1"/></testsuites>'))
        self.assertIsNone(junit_result(b'<testsuite tests="0"/>'))
        self.assertIsNone(junit_result(b'<testsuite><testcase><skipped/></testcase></testsuite>'))
        with self.assertRaises(ValueError):
            junit_result(b'<!DOCTYPE testsuite [<!ENTITY x "bad">]><testsuite/>')
        with self.assertRaises(ValueError):
            junit_result(b'<testsuite tests="-1"/>')

    def test_junit_declared_failures_and_incomplete_cases_cannot_pass(self):
        self.assertFalse(junit_result(b'<testsuite tests="1" failures="1"><testcase/></testsuite>'))
        with self.assertRaises(ValueError):
            junit_result(b'<testsuite tests="2"><testcase/></testsuite>')

    def test_reader_rejects_escape_symlinks_wrong_hash_and_fifo(self):
        artifact = self.root / 'ok.log';artifact.write_bytes(b'hello')
        digest = hashlib.sha256(b'hello').hexdigest()
        reader = EvidenceReader(self.root)
        self.assertEqual(reader.read('ok.log', digest), b'hello')
        (self.root / 'link').symlink_to(artifact)
        (self.root / 'dirlink').symlink_to(self.root, target_is_directory=True)
        for ref in ('../ok.log', str(artifact), 'https://example.test/file', 'link', 'dirlink/ok.log'):
            with self.subTest(ref=ref), self.assertRaises((ValueError, OSError)):
                reader.read(ref, digest)
        with self.assertRaises(ValueError):
            reader.read('ok.log', '0'*64)
        import os
        os.mkfifo(self.root / 'pipe')
        with self.assertRaises(ValueError):
            reader.read('pipe', digest)
