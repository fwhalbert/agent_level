import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / 'auto_eval_session_notice.py'
INSTRUCTIONS = (SCRIPT.parent / 'AGENTS.md').read_text()


class SessionNoticeTests(unittest.TestCase):
    def run_hook(self, cwd, source='startup'):
        return subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps({'cwd': str(cwd), 'source': source}),
                              text=True, capture_output=True, check=True).stdout

    def test_enabled_workspace_and_nested_directory(self):
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root)
            (workspace / 'AGENTS.md').write_text(INSTRUCTIONS)
            nested = workspace / 'nested'
            nested.mkdir()
            result = json.loads(self.run_hook(nested))
            self.assertEqual(result['systemMessage'], 'Auto eval enabled.')
            self.assertEqual(result['hookSpecificOutput']['hookEventName'], 'SessionStart')

    def test_disabled_and_non_startup_are_silent(self):
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root)
            self.assertEqual(self.run_hook(workspace), '')
            (workspace / 'CLAUDE.md').write_text('@AUTO_EVALUATION.md')
            self.assertEqual(self.run_hook(workspace), '')
            self.assertEqual(self.run_hook(workspace, 'resume'), '')

    def test_relative_absolute_and_cyclic_imports(self):
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root)
            rules = workspace / 'rules'
            rules.mkdir()
            canonical = rules / 'shared.md'
            canonical.write_text(INSTRUCTIONS)
            (workspace / 'CLAUDE.md').write_text('@AGENTS.md\n')
            agents = workspace / 'AGENTS.md'
            agents.write_text('@CLAUDE.md\n@rules/shared.md\n')
            self.assertIn('Auto eval enabled.', self.run_hook(workspace))
            agents.write_text(f'@CLAUDE.md\n@{canonical}\n')
            self.assertIn('Auto eval enabled.', self.run_hook(workspace))
            canonical.unlink()
            self.assertEqual(self.run_hook(workspace), '')

    def test_import_examples_inside_code_blocks_do_not_enable_notice(self):
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root)
            (workspace / 'example.md').write_text(INSTRUCTIONS)
            (workspace / 'AGENTS.md').write_text('```text\n@example.md\n```\n')
            self.assertEqual(self.run_hook(workspace), '')


if __name__ == '__main__':
    unittest.main()
