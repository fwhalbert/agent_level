"""Default baseline and log-derived level behavior across report formats."""
import json
from pathlib import Path
import subprocess
import sys

import assess as A
from assessment.logs import Metrics
from tests.test_assessment_core import TempCase


class TestObservedLevels(TempCase):
    def test_human_input_alone_does_not_establish_ai_activity(self):
        metrics = Metrics('codex')
        metrics.humanish_user = 3
        self.assertEqual(A.evaluate(metrics)['current'], 0)

    def test_source_entrypoint_defaults_to_target_project(self):
        source = Path(A.__file__).resolve()
        result = subprocess.run([sys.executable, str(source), '--source', 'codex',
            '--codex-dir', str(self.root / 'missing'), '--format', 'json', '-o', '-'],
            cwd=self.root, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)['reports']['codex']
        self.assertTrue(report['project_filter']['enabled'])
        self.assertEqual(report['current_level'], 0)

    def test_default_l0_survives_higher_levels_for_every_source(self):
        for source in ('claude', 'codex', 'combined'):
            for level in range(5):
                with self.subTest(source=source, level=level):
                    m = Metrics(source)
                    if level >= 1:
                        m.assistant = 1
                    if level >= 2:
                        m.edit_calls = 1
                    if level >= 3:
                        m.tool_calls, m.humanish_user = 50, 3
                        m.engineering_sessions.add('a')
                    if level >= 4:
                        m.engineering_sessions.update(('b', 'c'))
                        m.engineering_days.update(('2026-09-10', '2026-09-11'))
                    result = A.evaluate(m)
                    self.assertEqual(result['current'], level)
                    self.assertEqual(result['status'][0], 'DEFAULT')
                    self.assertTrue(all(c.ok for c in result['gates'][0]))
                    self.assertEqual(result['basis'], 'default' if level == 0 else 'observed')
                    for higher in (5, 6, 7):
                        self.assertEqual(result['status'][higher], 'NOT VERIFIED')
                        self.assertFalse(any(check.ok for check in result['gates'][higher]))
                    if level == 0:
                        self.assertIsNone(result['observed_level'])
                        self.assertEqual(result['next'], 1)
                        self.assertEqual(result['status'][1], 'NOT VERIFIED')

    def test_default_l0_cli_rendering(self):
        from html.parser import HTMLParser

        class BaselineParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.baselines = []

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'button' and attrs.get('id', '').startswith('level-') and attrs['id'].endswith('-0'):
                    self.baselines.append(attrs)

        for fmt in ('json', 'txt', 'md', 'html'):
            code, output, error = self.cli([
                '--claude-dir', str(self.root / 'missing-claude'),
                '--codex-dir', str(self.root / 'missing-codex'), '--format', fmt])
            self.assertEqual(code, 0, error)
            if fmt == 'json':
                for report in json.loads(output)['reports'].values():
                    self.assertEqual(report['current_level'], 0)
                    self.assertEqual(report['assessment_basis'], 'default')
                    self.assertIsNone(report['observed_level'])
                    self.assertEqual(report['levels']['L0']['status'], 'DEFAULT')
            elif fmt == 'html':
                self.assertIn('Default baseline', output)
                self.assertIn('默认达成', output)
                parser = BaselineParser()
                parser.feed(output)
                self.assertEqual(len(parser.baselines), 3)
                for attrs in parser.baselines:
                    self.assertIn('achieved', attrs['class'].split())
                    self.assertIn('current', attrs['class'].split())
            else:
                self.assertIn('Current Level : L0', output)
                self.assertIn('Basis        : default', output)
                self.assertIn('Achieved by default', output)
