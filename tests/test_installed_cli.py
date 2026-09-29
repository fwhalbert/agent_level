"""Offline installation checks; provide build wheels via AGENT_LEVEL_TEST_WHEELHOUSE."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class TestInstalledCLI(unittest.TestCase):
    def test_bootstrap_and_installed_commands(self):
        wheelhouse = os.environ.get('AGENT_LEVEL_TEST_WHEELHOUSE')
        if not wheelhouse:
            self.skipTest('set AGENT_LEVEL_TEST_WHEELHOUSE to local setuptools and wheel wheels')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            original = Path(__file__).resolve().parents[1]
            for name in ('pyproject.toml', 'README.md', 'AGENTS.md', 'bootstrap.py',
                         'assess.py', 'agent_level_record.py', 'auto_eval_session_notice.py'):
                shutil.copy2(original / name, source / name)
            shutil.copytree(original / 'assessment', source / 'assessment',
                            ignore=shutil.ignore_patterns('__pycache__'))
            workspace = root / 'workspace'
            workspace.mkdir()
            venv = workspace / '.venv'
            env = dict(os.environ, PIP_NO_INDEX='1', PIP_FIND_LINKS=str(Path(wheelhouse).resolve()),
                       PIP_DISABLE_PIP_VERSION_CHECK='1')
            env.pop('PYTHONPATH', None)

            def run(*argv, input=None):
                result = subprocess.run(argv, cwd=workspace, env=env, input=input,
                                        text=True, capture_output=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

            run(sys.executable, '-m', 'venv', str(venv))
            python = str(venv / 'bin' / 'python')
            # First exercise pip's isolated build in a venv without a backend.
            run(sys.executable, str(source / 'bootstrap.py'), '--project-dir', str(workspace))
            self.assertIn(f'@{source / "AGENTS.md"}', (workspace / 'AGENTS.md').read_text())
            self.assertNotIn('## Start before work', (workspace / 'AGENTS.md').read_text())
            # Then exercise bootstrap's existing-build-tooling branch.
            run(python, '-m', 'pip', 'install', 'setuptools>=64', 'wheel')
            configs = [workspace / name for name in ('AGENTS.md', 'CLAUDE.md',
                       '.codex/hooks.json', '.claude/settings.json')]
            before = [path.read_bytes() for path in configs]
            run(sys.executable, str(source / 'bootstrap.py'), '--project-dir', str(workspace))
            self.assertEqual([path.read_bytes() for path in configs], before)
            bin_dir = venv / 'bin'
            self.assertEqual(run(str(bin_dir / 'agent-level-assess'), '--version').strip(), '1.0.0')
            self.assertEqual(run(str(bin_dir / 'agent_level_assess.py'), '--version').strip(), '1.0.0')
            notice = run(str(bin_dir / 'agent-level-session-notice'),
                         input=json.dumps({'source': 'startup', 'cwd': str(workspace)}))
            self.assertEqual(json.loads(notice)['systemMessage'], 'Auto eval enabled.')
            recorder = str(bin_dir / 'agent-level-record')
            task_dir = run(recorder, 'start', '--repo', str(workspace), '--source', 'codex',
                           '--model', 'synthetic-test', '--criteria', 'Installed command smoke check',
                           '--', python, '-c', 'assert sum([1, 2, 3]) == 6').strip()
            self.assertTrue(json.loads(run(recorder, 'finish', '--task-dir', task_dir))['passed'])
            empty_logs = root / 'empty-logs'
            empty_logs.mkdir()
            report = json.loads(run(str(bin_dir / 'agent-level-assess'), '--source', 'codex',
                                    '--codex-dir', str(empty_logs), '--format', 'json', '-o', '-'))
            counts = report['reports']['codex']['anthropic_evaluation']['counts']
            self.assertEqual(counts['verified_trials'], 1)
            self.assertEqual(counts['successful_trials'], 1)
