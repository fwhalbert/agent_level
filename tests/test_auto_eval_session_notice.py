import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / 'auto_eval_session_notice.py'


class SessionNoticeTests(unittest.TestCase):
    def run_hook(self, cwd, source='startup'):
        return subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps({'cwd': str(cwd), 'source': source}),
                              text=True, capture_output=True, check=True).stdout

    def test_enabled_workspace_and_nested_directory(self):
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root)
            (workspace / 'AGENTS.md').write_text('Read /tools/agent_level/AUTO_EVALUATION.md')
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
            self.assertEqual(self.run_hook(workspace, 'resume'), '')


if __name__ == '__main__':
    unittest.main()
