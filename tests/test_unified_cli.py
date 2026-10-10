"""Public CLI behavior using isolated projects and synthetic activity."""
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from assessment.cli import main
from examples.generate_report import sample_bundle, main as generate_example


class TestUnifiedCLI(unittest.TestCase):
    def installed_commands(self, environment):
        directory = environment / 'bin'
        directory.mkdir(parents=True, exist_ok=True)
        for command in ('agent-level', 'agent-level-record', 'agent-level-session-notice'):
            (directory / command).touch()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        previous = Path.cwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(self.root)
        self.empty = ['--claude-dir', str(self.root / 'no-claude'),
                      '--codex-dir', str(self.root / 'no-codex'), '--no-auto-evals']

    def run_cli(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            try:
                status = main(list(args))
            except SystemExit as exc:
                status = exc.code
        return status, out.getvalue(), err.getvalue()

    def test_help_and_version(self):
        for command in ([], ['assess'], ['compare'], ['record'], ['setup']):
            with self.subTest(command=command):
                status, out, _ = self.run_cli(*command, '--help')
                self.assertEqual(status, 0)
                self.assertIn('usage:', out)
        self.assertEqual(self.run_cli('--version')[:2], (0, '1.0.0\n'))
        self.assertIn('--source', self.run_cli('assess', '--help')[1])
        self.assertIn('--eval-results', self.run_cli('compare', '--help')[1])
        self.assertIn('--project-dir', self.run_cli('setup', '--help')[1])
        self.assertNotIn('bootstrap.py', self.run_cli('--help')[1])

    def test_setup_uses_active_installation_and_preserves_workspace_configuration(self):
        environment = self.root / 'tool-env'
        notice = environment / 'bin/agent-level-session-notice'
        self.installed_commands(environment)
        (self.root / 'AGENTS.md').write_text('Keep these project rules.\n')
        hook = self.root / '.codex/hooks.json'
        hook.parent.mkdir()
        existing = {'hooks': {'SessionStart': [{'hooks': [
            {'type': 'command', 'command': 'custom-notice'}]}]}}
        hook.write_text(json.dumps(existing))
        with patch('bootstrap.sys.prefix', str(environment)), patch('bootstrap.install_package') as install:
            status, out, err = self.run_cli('setup')
            self.assertEqual(status, 0, err)
            install.assert_not_called()
            self.assertIn('agent-level', out)
            self.assertIn('/hooks', out)
            config_paths = [self.root / 'AGENTS.md', self.root / 'CLAUDE.md', hook,
                            self.root / '.claude/settings.json']
            before = [p.read_bytes() for p in config_paths]
            self.assertEqual(self.run_cli('setup')[0], 0)
            self.assertEqual([p.read_bytes() for p in config_paths], before)
        self.assertIn('Keep these project rules.', (self.root / 'AGENTS.md').read_text())
        hooks = json.loads(hook.read_text())['hooks']['SessionStart']
        self.assertEqual(hooks[0], existing['hooks']['SessionStart'][0])
        self.assertEqual(hooks[1]['hooks'][0]['command'], str(notice))
        self.assertFalse((self.root / '.venv').exists())

    def test_setup_explicit_venv_installs_from_checkout(self):
        environment = self.root / 'selected-env'
        notice = environment / 'bin/agent-level-session-notice'
        self.installed_commands(environment)
        with patch('bootstrap.install_package') as install:
            status, _, err = self.run_cli('setup', '--venv', str(environment))
            self.assertEqual(status, 0, err)
            install.assert_called_once_with(Path(__file__).resolve().parents[1], environment)

    def test_setup_installs_in_an_active_venv_that_has_no_cli(self):
        environment = self.root / 'empty-env'
        environment.mkdir()
        with patch('bootstrap.sys.prefix', str(environment)), \
                patch('bootstrap.install_package', side_effect=lambda source, venv: self.installed_commands(venv)) as install:
            status, _, err = self.run_cli('setup')
            self.assertEqual(status, 0, err)
            install.assert_called_once_with(Path(__file__).resolve().parents[1], environment)

    def test_setup_creates_default_environment_and_prints_a_direct_report_command(self):
        workspace = self.root / 'project with spaces'
        workspace.mkdir()
        environment = workspace / '.venv'
        with patch('bootstrap.sys.prefix', sys.base_prefix), \
                patch('bootstrap.install_package', side_effect=lambda source, venv: self.installed_commands(venv)) as install:
            status, out, err = self.run_cli('setup', '--project-dir', str(workspace))
            self.assertEqual(status, 0, err)
            install.assert_called_once_with(Path(__file__).resolve().parents[1], environment)
        command = next(line.strip() for line in out.splitlines() if line.startswith('  '))
        self.assertEqual(shlex.split(command), [str(environment / 'bin/agent-level'),
                                               '--project-dir', str(workspace)])
        self.assertNotIn('source ', out)
        self.assertNotIn('  cd ', out)
        instructions = (workspace / 'AGENTS.md').read_text()
        self.assertNotIn('## agent_level: installed commands', instructions)
        self.assertNotIn(str(environment), instructions)

    def test_checkout_launcher_runs_without_package_installation(self):
        launcher = Path(__file__).resolve().parents[1] / 'agent-level'
        for args in (['--version'], ['setup', '--help']):
            result = subprocess.run([sys.executable, '-S', str(launcher), *args],
                                    cwd=self.root, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('1.0.0' if args == ['--version'] else 'Install Agent Level', result.stdout)

    def test_setup_missing_project_fails_without_configuration(self):
        status, _, err = self.run_cli('setup', '--project-dir', str(self.root / 'absent'))
        self.assertEqual(status, 2)
        self.assertIn('setup failed', err)
        self.assertFalse((self.root / 'AGENTS.md').exists())

    def test_default_generates_branded_html_without_logs(self):
        status, out, err = self.run_cli(*self.empty)
        self.assertEqual((status, out), (0, ''))
        reports = list(self.root.glob('out/agent_level/*/agent-level.html'))
        self.assertEqual(len(reports), 1)
        html = reports[0].read_text()
        self.assertIn('>Agent Level</span></h1>', html)
        self.assertIn('Default baseline', html)
        self.assertIn(reports[0].as_uri(), err)
        self.assertFalse((self.root / 'AGENTS.md').exists())

    def test_json_stdout_default_project_and_explicit_subcommand(self):
        for prefix in ([], ['assess']):
            status, out, err = self.run_cli(*prefix, *self.empty, '--format', 'json', '-o', '-')
            self.assertEqual(status, 0)
            bundle = json.loads(out)
            self.assertEqual(bundle['report_name'], 'Agent Level')
            for report in bundle['reports'].values():
                self.assertEqual(report['current_level'], 0)
                self.assertIsNone(report['observed_level'])
                self.assertEqual(report['levels']['L0']['status'], 'DEFAULT')
                self.assertTrue(report['project_filter']['enabled'])
            self.assertIn('[progress]', err)

    def test_synthetic_activity_uses_existing_rules_and_project_filter(self):
        fixture = Path(__file__).resolve().parents[1] / 'examples/sample-data/codex'
        target = tempfile.TemporaryDirectory()
        self.addCleanup(target.cleanup)
        logs = self.root / 'logs/sessions'
        logs.mkdir(parents=True)
        for path in (fixture / 'sessions').glob('*.jsonl'):
            (logs / path.name).write_text(path.read_text().replace('/synthetic/agent-level-demo', target.name))
        args = ['assess', '--source', 'codex', '--codex-dir', str(logs.parent),
                '--no-auto-evals', '--format', 'json', '-o', '-']
        status, out, _ = self.run_cli(*args)
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out)['reports']['codex']['current_level'], 0)
        status, out, _ = self.run_cli(*args, '--project-dir', target.name)
        self.assertEqual(status, 0)
        report = json.loads(out)['reports']['codex']
        self.assertEqual(report['current_level'], 4)
        self.assertEqual(report['anthropic_evaluation']['counts']['successful_trials'], 0)
        for level in (5, 6, 7):
            self.assertEqual(report['levels'][f'L{level}']['status'], 'NOT VERIFIED')

    def test_custom_report_name_and_explicit_output(self):
        status, _, _ = self.run_cli(*self.empty, '--name=My Report', '-o', 'custom.html')
        self.assertEqual(status, 0)
        self.assertIn('>My Report</span></h1>', Path('custom.html').read_text())

    def test_compare_selects_existing_view_without_claiming_improvement(self):
        status, html, _ = self.run_cli('compare', *self.empty, '-o', '-')
        self.assertEqual(status, 0)
        self.assertIn('value="improvement" selected', html)
        self.assertIn('data-method-view="levels" hidden', html)
        status, output, _ = self.run_cli('compare', *self.empty, '--format', 'json', '-o', '-')
        self.assertEqual(status, 0)
        comparison = json.loads(output)['reports']['combined']['self_improvement_evaluation']
        self.assertEqual(comparison['comparisons'], [])
        self.assertIn('No predefined controlled before/after comparison is available.', html)

    def test_record_start_and_unknown_preserves_acceptance_argv(self):
        status, out, _ = self.run_cli(
            'record', 'start', '--repo', str(self.root), '--source', 'codex',
            '--model', 'synthetic', '--criteria', 'Synthetic routing check',
            '--', 'python', '-c', 'assert 2 + 2 == 4')
        self.assertEqual(status, 0)
        directory = Path(out.strip())
        self.assertTrue(directory.is_dir())
        task = json.loads((directory / 'results.json').read_text())['tasks'][0]
        self.assertEqual(task['check_command'], ['python', '-c', 'assert 2 + 2 == 4'])
        status, _, _ = self.run_cli('record', 'finish', '--task-dir', str(directory),
                                    '--unknown', 'Routing test does not run acceptance')
        self.assertEqual(status, 2)
        self.assertTrue((directory / 'results.json').is_file())

    def test_compare_explicit_import_keeps_separate_scope_and_synthetic_limits(self):
        payload = {'schema_version': '1.1', 'synthetic': True, 'tasks': [],
                   'improvement_comparisons': [{'source': 'codex'}]}
        imported = self.root / 'comparison.json'
        imported.write_text(json.dumps(payload))
        status, output, _ = self.run_cli(
            'compare', *self.empty[:-1], '--eval-results', str(imported),
            '--evidence-root', str(self.root), '--format', 'json', '-o', '-')
        self.assertEqual(status, 0)
        bundle = json.loads(output)
        self.assertFalse(bundle['project_task_records']['enabled'])
        report = bundle['reports']['codex']
        self.assertFalse(report['project_filter']['enabled'])
        comparison = report['self_improvement_evaluation']['comparisons'][0]
        self.assertEqual(comparison['status'], 'insufficient_evidence')
        self.assertEqual(comparison['reason'], 'synthetic_data')

    def test_invalid_commands_options_and_dates_are_errors(self):
        for args in (['not-a-command'], ['assess', '--bad-flag'],
                     ['assess', '--days', '0'], ['record', 'not-an-action']):
            with self.subTest(args=args):
                self.assertEqual(self.run_cli(*args)[0], 2)


class TestSyntheticExample(unittest.TestCase):
    def test_repeatable_output_and_no_raw_activity(self):
        self.assertEqual(sample_bundle(), sample_bundle())
        with tempfile.TemporaryDirectory() as temporary:
            generate_example(['--output-dir', temporary])
            output = Path(temporary)
            before = {p.name: p.read_bytes() for p in output.iterdir()}
            generate_example(['--output-dir', temporary])
            self.assertEqual(before, {p.name: p.read_bytes() for p in output.iterdir()})
            for data in before.values():
                for raw in (b'Synthetic task:', b'synthetic-session-', b'rg example README.md',
                            b'/synthetic/agent-level-demo'):
                    self.assertNotIn(raw, data)
            report = json.loads(before['agent-level.json'])
            self.assertTrue(report['synthetic'])
            self.assertEqual(report['reports']['codex']['current_level'], 4)
