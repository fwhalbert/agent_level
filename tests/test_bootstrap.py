import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

from auto_eval_session_notice import enabled, INSTRUCTION_START, INSTRUCTION_END
from bootstrap import IMPORT_END, IMPORT_START, assess_entrypoint_content, enable_workspace, main


SOURCE = Path(__file__).resolve().parents[1]


class TestBootstrap(unittest.TestCase):
    def test_packaged_workflow_matches_canonical_instructions(self):
        source = (SOURCE / 'AGENTS.md').read_text()
        section = source[source.index(INSTRUCTION_START):source.index(INSTRUCTION_END) + len(INSTRUCTION_END)]
        self.assertEqual((SOURCE / 'assessment/task_evidence.md').read_text(), section + '\n')

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name) / "workspace"
        self.workspace.mkdir()
        self.venv = self.workspace / ".venv"
        self.venv.mkdir()

    def test_new_workspace_gets_instruction_and_hooks_once(self):
        enable_workspace(self.workspace, self.venv, SOURCE)
        self.assertFalse((self.workspace / "agent_level_assess.py").exists())
        self.assertFalse((self.workspace / "assess.py").exists())
        self.assertFalse((self.workspace / '.gitignore').exists())
        first = (self.workspace / "AGENTS.md").read_text()
        first_claude = (self.workspace / "CLAUDE.md").read_text()
        self.assertTrue(enabled(self.workspace))
        self.assertTrue(first.startswith("## agent_level: automatic task evidence\n\n"
                                        "Read and follow the task evidence workflow in:\n"
                                        f"@{SOURCE / 'AGENTS.md'}\n"))
        self.assertNotIn("## agent_level: installed commands", first)
        self.assertNotIn(str(self.venv), first)
        self.assertNotIn("agent_level_record.py start", first)
        self.assertNotIn("<!-- agent-level:task-evidence:start -->", first)
        self.assertEqual(first_claude, "@AGENTS.md\n")
        for path in (self.workspace / ".codex" / "hooks.json",
                     self.workspace / ".claude" / "settings.json"):
            data = json.loads(path.read_text())
            self.assertEqual(len(data["hooks"]["SessionStart"]), 1)
            self.assertIn("agent-level-session-notice",
                          data["hooks"]["SessionStart"][0]["hooks"][0]["command"])
        enable_workspace(self.workspace, self.venv, SOURCE)
        self.assertFalse((self.workspace / '.gitignore').exists())
        self.assertEqual((self.workspace / "AGENTS.md").read_text(), first)
        self.assertEqual((self.workspace / "CLAUDE.md").read_text(), first_claude)
        for path in (self.workspace / ".codex" / "hooks.json",
                     self.workspace / ".claude" / "settings.json"):
            self.assertEqual(len(json.loads(path.read_text())["hooks"]["SessionStart"]), 1)

    def test_existing_gitignore_is_preserved_exactly(self):
        ignore = self.workspace / '.gitignore'
        original = b'keep-existing-pattern\r\n.codex\r\n.claude\r\n/out/agent_level/\r\n'
        ignore.write_bytes(original)
        enable_workspace(self.workspace, self.venv, SOURCE)
        self.assertEqual(ignore.read_bytes(), original)
        enable_workspace(self.workspace, self.venv, SOURCE)
        self.assertEqual(ignore.read_bytes(), original)

    def test_bootstrap_does_not_add_git_ignore_rules(self):
        subprocess.run(['git', 'init', '--quiet', str(self.workspace)], check=True)
        enable_workspace(self.workspace, self.venv, SOURCE)
        for agent in ('codex', 'claude'):
            relative = f'.{agent}/agent_level/tasks/example/check.log'
            path = self.workspace / relative
            path.parent.mkdir(parents=True)
            path.write_text('synthetic acceptance output')
            result = subprocess.run(['git', '-c', 'core.excludesFile=/dev/null',
                                     'check-ignore', '--', relative], cwd=self.workspace,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
        for relative in ('.codex/hooks.json', '.claude/settings.json',
                         'out/agent_level/example.html'):
            result = subprocess.run(['git', '-c', 'core.excludesFile=/dev/null',
                                     'check-ignore', '--', relative], cwd=self.workspace,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)

    def test_existing_instructions_and_settings_are_preserved(self):
        (self.workspace / "AGENTS.md").write_text("Keep this rule.\n")
        (self.workspace / "CLAUDE.md").write_text("Keep this Claude rule.\n")
        path = self.workspace / ".codex" / "hooks.json"
        path.parent.mkdir()
        legacy = f"python3 {SOURCE / 'auto_eval_session_notice.py'}"
        path.write_text(json.dumps({"other": 1, "hooks": {"SessionStart": [
            {"hooks": [{"type": "command", "command": legacy, "timeout": 5}]}]}}))
        enable_workspace(self.workspace, self.venv, SOURCE)
        self.assertIn("Keep this rule.", (self.workspace / "AGENTS.md").read_text())
        self.assertIn(f"@{SOURCE / 'AGENTS.md'}", (self.workspace / "AGENTS.md").read_text())
        self.assertEqual((self.workspace / "CLAUDE.md").read_text(),
                         "Keep this Claude rule.\n\n@AGENTS.md\n")
        data = json.loads(path.read_text())
        self.assertEqual(data["other"], 1)
        self.assertEqual(len(data["hooks"]["SessionStart"]), 1)
        self.assertIn("agent-level-session-notice",
                      data["hooks"]["SessionStart"][0]["hooks"][0]["command"])

    def test_legacy_link_is_replaced_and_custom_rules_are_kept(self):
        (self.workspace / "AGENTS.md").write_text(
            "Keep this rule.\n\n## Automatic Task Evidence\n\n"
            "For substantive engineering tasks, follow "
            "[task evidence instructions](../../tools/agent_level/AUTO_EVALUATION.md).\n")
        enable_workspace(self.workspace, self.venv, SOURCE)
        content = (self.workspace / "AGENTS.md").read_text()
        self.assertTrue(content.startswith("Keep this rule.\n\n"))
        self.assertNotIn("AUTO_EVALUATION.md", content)
        self.assertEqual(content.count("## agent_level: automatic task evidence"), 1)
        self.assertTrue(enabled(self.workspace))
        enable_workspace(self.workspace, self.venv, SOURCE)
        self.assertEqual((self.workspace / "AGENTS.md").read_text(), content)

    def test_marked_import_migrates_without_changing_surrounding_rules(self):
        agents = self.workspace / "AGENTS.md"
        before = "Keep this rule.\n\n"
        after = "\nKeep this too.\n\n## Project rules\nUse the project venv.\n"
        agents.write_text(before + f"{IMPORT_START}\n## Automatic Task Evidence\n\n"
                          "Read and follow the task evidence workflow in:\n"
                          f"@/old/source/AGENTS.md\n{IMPORT_END}\n" + after)
        enable_workspace(self.workspace, self.venv, SOURCE)
        content = agents.read_text()
        self.assertTrue(content.startswith(before + "## agent_level: automatic task evidence\n\n"
                                          "Read and follow the task evidence workflow in:\n"
                                          f"@{SOURCE / 'AGENTS.md'}\n"))
        self.assertTrue(content.endswith(after))
        self.assertNotIn('## agent_level: installed commands', content)
        self.assertNotIn(str(self.venv), content)
        self.assertTrue(enabled(self.workspace))
        enable_workspace(self.workspace, self.venv, SOURCE)
        self.assertEqual(agents.read_text(), content)

    def test_generated_project_launchers_are_removed_but_custom_scripts_remain(self):
        old_path = self.workspace / "assess.py"
        new_path = self.workspace / "agent_level_assess.py"
        old_path.write_text(assess_entrypoint_content(self.venv))
        other_venv = self.workspace / "different-venv"
        new_path.write_text(assess_entrypoint_content(other_venv))
        enable_workspace(self.workspace, self.venv, SOURCE)
        self.assertFalse(old_path.exists())
        self.assertFalse(new_path.exists())
        old_path.write_text("custom script\n")
        new_path.write_text(assess_entrypoint_content(self.venv) + "# changed\n")
        enable_workspace(self.workspace, self.venv, SOURCE)
        self.assertEqual(old_path.read_text(), "custom script\n")
        self.assertTrue(new_path.read_text().endswith("# changed\n"))

    def test_copied_instructions_migrate_to_reference_and_track_source_updates(self):
        source = Path(self.temporary.name) / 'source with spaces'
        source.mkdir()
        canonical = source / 'AGENTS.md'
        canonical.write_text((SOURCE / 'AGENTS.md').read_text())
        agents = self.workspace / 'AGENTS.md'
        agents.write_text('Before.\n\n' + canonical.read_text() + '\nAfter.\n')
        enable_workspace(self.workspace, self.venv, source)
        content = agents.read_text()
        self.assertTrue(content.startswith('Before.\n\n'))
        self.assertTrue(content.endswith('\nAfter.\n'))
        self.assertIn(f'@{canonical}\n', content)
        self.assertNotIn('## Start before work', content)
        self.assertTrue(enabled(self.workspace))
        canonical.write_text('Rules removed.\n')
        self.assertFalse(enabled(self.workspace))
        self.assertEqual(agents.read_text(), content)

    def test_same_checkout_does_not_replace_canonical_instructions(self):
        canonical = self.workspace / 'AGENTS.md'
        original = (SOURCE / 'AGENTS.md').read_text()
        canonical.write_text(original)
        enable_workspace(self.workspace, self.venv, self.workspace)
        self.assertEqual(canonical.read_text(), original)

    def test_relocation_updates_import_and_notice_hooks_only(self):
        path = self.workspace / '.codex' / 'hooks.json'
        path.parent.mkdir()
        custom = {'type': 'command', 'command': 'echo agent-level-session-notice', 'timeout': 12}
        path.write_text(json.dumps({'hooks': {'SessionStart': [{'hooks': [custom]}]}}))
        enable_workspace(self.workspace, self.venv, SOURCE)
        agents = self.workspace / 'AGENTS.md'
        before = 'Keep this rule.\n\n'
        after = '\nKeep this too.\n\n## Project rules\nUse the project venv.\n'
        commands = ("\n## agent_level: installed commands\n\n"
                    "Use these commands without activating a virtual environment:\n"
                    f"- Recorder: `{self.venv / 'bin' / 'agent-level-record'}` (append the workflow arguments).\n"
                    f"- Report: `{self.venv / 'bin' / 'agent-level'} --project-dir {self.workspace}`.\n")
        agents.write_text(before + agents.read_text() + commands + after)
        relocated = Path(self.temporary.name) / 'relocated'
        relocated.mkdir()
        (relocated / 'AGENTS.md').write_text((SOURCE / 'AGENTS.md').read_text())
        venv = self.workspace / 'new venv'
        venv.mkdir()
        enable_workspace(self.workspace, venv, relocated)
        content = (self.workspace / 'AGENTS.md').read_text()
        self.assertEqual(content.count('## agent_level: automatic task evidence'), 1)
        self.assertNotIn('<!-- agent-level:', content)
        self.assertTrue(content.startswith(before))
        self.assertTrue(content.endswith(after))
        self.assertIn(f'@{relocated / "AGENTS.md"}\n', content)
        self.assertNotIn(f'@{SOURCE / "AGENTS.md"}', content)
        self.assertNotIn('## agent_level: installed commands', content)
        self.assertNotIn(str(venv), content)
        self.assertNotIn(str(self.venv), content)
        enable_workspace(self.workspace, venv, relocated)
        self.assertEqual(agents.read_text(), content)
        for config in (path, self.workspace / '.claude' / 'settings.json'):
            items = [item for entry in json.loads(config.read_text())['hooks']['SessionStart']
                     for item in entry['hooks']]
            notices = [item for item in items if item != custom]
            self.assertEqual(len(notices), 1)
            self.assertIn(str(venv), notices[0]['command'])
        self.assertEqual(json.loads(path.read_text())['hooks']['SessionStart'][0]['hooks'], [custom])

    def test_bootstrap_accepts_project_dir(self):
        python = self.venv / "bin" / "python"
        python.parent.mkdir()
        python.touch()
        with patch("bootstrap.subprocess.run") as run:
            run.return_value.returncode = 0
            self.assertEqual(main(["--project-dir", str(self.workspace)]), 0)
            previous = Path.cwd()
            try:
                os.chdir(self.workspace)
                self.assertEqual(main(["--project-dir"]), 0)
            finally:
                os.chdir(previous)
        self.assertFalse((self.workspace / "agent_level_assess.py").exists())


if __name__ == "__main__":
    unittest.main()
