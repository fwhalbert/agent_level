import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from auto_eval_session_notice import enabled, INSTRUCTION_START, INSTRUCTION_END
from bootstrap import IMPORT_END, IMPORT_START, enable_instructions, main


SOURCE = Path(__file__).resolve().parents[1]


class TestBootstrap(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.codex_home = self.root / 'codex home'

    def test_packaged_workflow_matches_canonical_instructions(self):
        source = (SOURCE / 'AGENTS.md').read_text()
        section = source[source.index(INSTRUCTION_START):source.index(INSTRUCTION_END) + len(INSTRUCTION_END)]
        self.assertEqual((SOURCE / 'assessment/task_evidence.md').read_text(), section + '\n')

    def test_global_setup_creates_only_one_reference_and_preserves_rules(self):
        self.codex_home.mkdir()
        agents = self.codex_home / 'AGENTS.md'
        original = 'Keep these personal rules.\n'
        agents.write_text(original)
        agents.chmod(0o640)
        enable_instructions(self.codex_home, SOURCE)
        expected = (original + '\n## agent_level: automatic task evidence\n\n'
                    'Read and follow the task evidence workflow in:\n'
                    f'@{SOURCE / "AGENTS.md"}\n')
        self.assertEqual(agents.read_text(), expected)
        self.assertEqual(agents.stat().st_mode & 0o777, 0o640)
        self.assertEqual([p.name for p in self.codex_home.iterdir()], ['AGENTS.md'])
        self.assertTrue(enabled(self.codex_home))
        enable_instructions(self.codex_home, SOURCE)
        self.assertEqual(agents.read_text(), expected)

    def test_relocation_replaces_reference_and_removes_old_command_block(self):
        enable_instructions(self.codex_home, SOURCE)
        agents = self.codex_home / 'AGENTS.md'
        before = 'Keep this rule.\n\n'
        after = '\nKeep this too.\n'
        commands = ('\n## agent_level: installed commands\n\n'
                    'Use these commands without activating a virtual environment:\n'
                    '- Recorder: `/old/venv/bin/agent-level-record`.\n'
                    '- Report: `/old/venv/bin/agent-level`.\n')
        agents.write_text(before + agents.read_text() + commands + after)
        relocated = self.root / 'source with spaces'
        relocated.mkdir()
        canonical = relocated / 'AGENTS.md'
        canonical.write_text((SOURCE / 'AGENTS.md').read_text())
        enable_instructions(self.codex_home, relocated)
        content = agents.read_text()
        self.assertTrue(content.startswith(before))
        self.assertTrue(content.endswith(after))
        self.assertEqual(content.count('## agent_level: automatic task evidence'), 1)
        self.assertIn(f'@{canonical}\n', content)
        self.assertNotIn(f'@{SOURCE / "AGENTS.md"}', content)
        self.assertNotIn('/old/venv', content)
        enable_instructions(self.codex_home, relocated)
        self.assertEqual(agents.read_text(), content)
        canonical.write_text('Workflow removed.\n')
        self.assertFalse(enabled(self.codex_home))

    def test_copied_and_marked_workflows_migrate_without_losing_other_rules(self):
        self.codex_home.mkdir()
        agents = self.codex_home / 'AGENTS.md'
        source = (SOURCE / 'AGENTS.md').read_text()
        copied = source[source.index(INSTRUCTION_START):source.index(INSTRUCTION_END) + len(INSTRUCTION_END)]
        marked = f'{IMPORT_START}\n@/old/source/AGENTS.md\n{IMPORT_END}'
        for old in (copied, marked):
            with self.subTest(old=old[:50]):
                agents.write_text(f'Before.\n\n{old}\n\nAfter.\n')
                enable_instructions(self.codex_home, SOURCE)
                content = agents.read_text()
                self.assertTrue(content.startswith('Before.\n\n'))
                self.assertTrue(content.endswith('\nAfter.\n'))
                self.assertIn(f'@{SOURCE / "AGENTS.md"}\n', content)
                self.assertNotIn('<!-- agent-level:', content)

    def test_legacy_link_migrates_to_global_reference(self):
        self.codex_home.mkdir()
        agents = self.codex_home / 'AGENTS.md'
        agents.write_text('Keep this rule.\n\n## Automatic Task Evidence\n\n'
                          'For substantive engineering tasks, follow '
                          '[task evidence instructions](/old/AUTO_EVALUATION.md).\n')
        enable_instructions(self.codex_home, SOURCE)
        content = agents.read_text()
        self.assertTrue(content.startswith('Keep this rule.\n\n'))
        self.assertNotIn('AUTO_EVALUATION.md', content)
        self.assertIn(f'@{SOURCE / "AGENTS.md"}\n', content)

    def test_same_checkout_keeps_canonical_instructions(self):
        canonical = self.root / 'AGENTS.md'
        original = (SOURCE / 'AGENTS.md').read_text()
        canonical.write_text(original)
        enable_instructions(self.root, self.root)
        self.assertEqual(canonical.read_text(), original)

    def test_symlinked_global_file_is_not_replaced(self):
        self.codex_home.mkdir()
        target = self.root / 'personal.md'
        target.write_text('Keep this.\n')
        (self.codex_home / 'AGENTS.md').symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            enable_instructions(self.codex_home, SOURCE)
        self.assertEqual(target.read_text(), 'Keep this.\n')

    def test_incomplete_workflow_is_not_overwritten(self):
        self.codex_home.mkdir()
        agents = self.codex_home / 'AGENTS.md'
        original = 'Keep this.\n' + IMPORT_START + '\n'
        agents.write_text(original)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            enable_instructions(self.codex_home, SOURCE)
        self.assertEqual(agents.read_text(), original)

    def test_setup_defaults_to_global_home_without_modifying_project(self):
        project = self.root / 'project'
        project.mkdir()
        (project / 'AGENTS.md').write_text('Project rules.\n')
        previous = Path.cwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(project)
        with patch.dict(os.environ, {'CODEX_HOME': ''}), patch('bootstrap.Path.home', return_value=self.root), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([]), 0)
        self.assertTrue((self.root / '.codex/AGENTS.md').is_file())
        self.assertEqual([p.name for p in project.iterdir()], ['AGENTS.md'])
        self.assertEqual((project / 'AGENTS.md').read_text(), 'Project rules.\n')

    def test_explicit_codex_home_overrides_environment(self):
        configured = self.root / 'configured'
        with patch.dict(os.environ, {'CODEX_HOME': str(configured)}), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([]), 0)
            first = (configured / 'AGENTS.md').read_bytes()
            self.assertEqual(main(['--codex-home', str(self.codex_home)]), 0)
        self.assertEqual((configured / 'AGENTS.md').read_bytes(), first)
        self.assertEqual((self.codex_home / 'AGENTS.md').read_bytes(), first)

    def test_setup_without_checkout_fails_without_writing(self):
        with patch('bootstrap.__file__', str(self.root / 'bootstrap.py')), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(main(['--codex-home', str(self.codex_home)]), 2)
        self.assertIn('source checkout', err.getvalue())
        self.assertFalse(self.codex_home.exists())


if __name__ == '__main__':
    unittest.main()
