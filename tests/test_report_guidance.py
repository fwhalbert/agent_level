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
