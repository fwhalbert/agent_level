#!/usr/bin/env python3
"""
Regression tests for assess.py.

Uses synthetic fixtures without accessing real ~/.claude data.

    python3 -m unittest tests.test_level_assessment -v
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import assess as A
from assessment.logs import classify_bash, is_human_input, DELEGATION_TOOLS


def assistant(tools=(), cache_read=0, cache_creation=0, out=0, sidechain=False,
              ts="2026-09-10T10:00:00.000Z"):
    content = [{"type": "text", "text": "..."}]
    for name, inp in tools:
        content.append({"type": "tool_use", "id": "t", "name": name, "input": inp})
    return {
        "type": "assistant", "timestamp": ts, "sessionId": "s1",
        "isSidechain": sidechain,
        "message": {"role": "assistant", "model": "claude-opus-5", "content": content,
                    "usage": {"input_tokens": 1,
                              "cache_read_input_tokens": cache_read,
                              "cache_creation_input_tokens": cache_creation,
                              "output_tokens": out,
                              # Iterations mirror top-level data and must not be counted twice.
                              "iterations": [{"input_tokens": 1,
                                              "cache_read_input_tokens": cache_read,
                                              "cache_creation_input_tokens": cache_creation,
                                              "output_tokens": out}]}},
    }


def user(text, sidechain=False, meta=False, ts="2026-09-10T10:00:00.000Z"):
    return {"type": "user", "timestamp": ts, "sessionId": "s1",
            "isSidechain": sidechain, "isMeta": meta,
            "message": {"role": "user", "content": text}}


def tool_result(ts="2026-09-10T10:00:00.000Z"):
    return {"type": "user", "timestamp": ts, "sessionId": "s1", "isSidechain": False,
            "message": {"role": "user",
                        "content": [{"type": "tool_result", "content": "..."}]}}


def write_dir(records_by_file, stats=None) -> Path:
    root = Path(tempfile.mkdtemp(prefix="assessment-test-"))
    proj = root / "projects" / "-some-project"
    proj.mkdir(parents=True)
    for fname, recs in records_by_file.items():
        with (proj / fname).open("w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")
    if stats is not None:
        (root / "stats-cache.json").write_text(json.dumps(stats), encoding="utf-8")
    return root


def assess(root):
    m = A.scan(Path(root))
    return m, A.evaluate(m)


class TestBashClassifier(unittest.TestCase):
    CASES = [
        ("pytest -q", "test"), ("python3 -m pytest tests/", "test"),
        ("npm run test", "test"), ("cargo test --all", "test"),
        ("make check", "test"), ("make -j8", "build"),
        # Running a compiled binary is a verification step in embedded engineering.
        ("make -s run", "test"), ("make run-vad_v2", "test"),
        ("./test_v2_vs_wolf", "test"), ("./build/bin/vad_test in.bin", "test"),
        ("./install.sh", "other"), ("./build/bin/vad_v2 in.bin", "other"),
        ("cmake -B build && ninja -C build", "build"),
        ("west build -b nrf52840dk", "build"),
        ("git status", "git"), ("git commit -m x && git push", "git"),
        ("gh pr create --fill", "pr"), ("gh run watch 42", "ci"),
        ("rg -n pattern src/", "search"), ("find . -name '*.c'", "search"),
        ("cat file.txt", "read"), ("sed -n '1,40p' f.py", "read"),
        ("docker compose up -d", "docker"), ("kubectl get pods", "docker"),
        ("ssh host uptime", "ssh"), ("node server.js", "node"),
        ("python3 script.py", "python"), ("pip install -r req.txt", "python"),
        ("frobnicate --wibble", "other"), ("", "other"),
    ]

    def test_cases(self):
        for cmd, want in self.CASES:
            self.assertEqual(classify_bash(cmd), want, msg=cmd)

    def test_prefixes_stripped(self):
        self.assertEqual(classify_bash("sudo make install"), "build")
        self.assertEqual(classify_bash("timeout 110 python3 x.py"), "python")
        self.assertEqual(classify_bash("cd /repo && pytest"), "test")
        self.assertEqual(classify_bash("FOO=1 BAR=2 node a.js"), "node")

    def test_known_executable_paths_preserve_categories(self):
        cases = [
            ('/repo/.venv/bin/python -m unittest discover -s tests', 'test'),
            ('.venv/bin/python3.12 -m pytest -q', 'test'),
            ('"/repo with spaces/.venv/bin/python" -m unittest', 'test'),
            ('/repo/.venv/bin/pytest -q', 'test'),
            ('/usr/bin/env FOO=1 /repo/.venv/bin/python -m pytest', 'test'),
            ('PYTHON=/repo/.venv/bin/python git status', 'git'),
            ('RUNNER=/repo/.venv/bin/pytest echo ready', 'read'),
            ('/usr/bin/env PYTHON=/repo/.venv/bin/python python3 -m unittest', 'test'),
            ('/usr/bin/bash -lc "/repo/.venv/bin/pytest -q"', 'test'),
            ('/repo/.venv/bin/python script.py', 'python'),
            ('/usr/bin/make -j8', 'build'),
            ('/repo/bin/custom-tool --label pytest', 'other'),
            ('./build/bin/vad_test in.bin', 'test'),
        ]
        for command, category in cases:
            with self.subTest(command=command):
                self.assertEqual(classify_bash(command), category)

    def test_shell_scripts_and_recorder_finish(self):
        cases = [
            ('bash scripts/fast_build.sh --release', 'build'),
            ('/home/u/ws/scripts/fast_build.sh', 'build'),
            ('bash -lc "./scripts/fast_build.sh"', 'build'),
            ('bash ./run_tests.sh x', 'test'),
            ('sh scripts/check.sh', 'test'),
            ('scripts/run_tests.py -v', 'test'),
            ('bash scripts/info.sh', 'other'),
            ('scripts/rebuild_index.py', 'other'),
            ('scripts/checkout.sh', 'other'),
            ('bash -x deploy.sh', 'other'),
            ('cat scripts/test.sh', 'read'),
            ('.venv/bin/agent-level-record finish --task-dir /t', 'test'),
            ('agent-level record finish --task-dir /t', 'test'),
            ('agent-level-record finish --task-dir /t --unknown blocked', 'other'),
            ('agent-level-record start --repo /r -- true', 'other'),
        ]
        for command, category in cases:
            with self.subTest(command=command):
                self.assertEqual(classify_bash(command), category)

    def test_heredoc_body_ignored(self):
        # Heredoc bodies are data, not build commands.
        self.assertEqual(
            classify_bash("cat > build.sh <<'EOF'\n#!/bin/bash\nmake -j\nEOF"), "read")
        self.assertEqual(
            classify_bash("python3 - <<'PY'\nimport re\ngit status\nPY"), "python")

    def test_highest_priority_wins(self):
        self.assertEqual(classify_bash("grep -n x f && make && pytest"), "test")
        self.assertEqual(classify_bash("make -s rebuild && make -s run"), "test")

    def test_delegation_tools_match_spec(self):
        self.assertTrue({"Task", "Agent", "Workflow", "spawn_agent"} <= DELEGATION_TOOLS)


class TestHumanFilter(unittest.TestCase):
    def test_plain_text_is_human(self):
        self.assertTrue(is_human_input(user("Help me fix this bug")))

    def test_tool_result_is_not(self):
        self.assertFalse(is_human_input(tool_result()))

    def test_sidechain_and_meta_are_not(self):
        self.assertFalse(is_human_input(user("x", sidechain=True)))
        self.assertFalse(is_human_input(user("x", meta=True)))

    def test_ide_notification_is_not(self):
        self.assertFalse(is_human_input(user(
            "<ide_opened_file>The user opened /a/b.c in the IDE.</ide_opened_file>")))

    def test_local_command_stdout_is_not(self):
        self.assertFalse(is_human_input(user(
            "<local-command-stdout>Set model to Opus</local-command-stdout>")))

    def test_system_reminder_only_is_not(self):
        self.assertFalse(is_human_input(user("<system-reminder>note</system-reminder>")))

    def test_slash_command_is_human(self):
        self.assertTrue(is_human_input(user(
            "<command-name>/model</command-name><command-args></command-args>")))

    def test_real_text_beside_ide_noise_is_human(self):
        self.assertTrue(is_human_input(user(
            "<ide_opened_file>x</ide_opened_file>\nContinue fixing the tests")))

    def test_image_block_is_human(self):
        rec = user("")
        rec["message"]["content"] = [{"type": "image", "source": {}}]
        self.assertTrue(is_human_input(rec))

    def test_assistant_record_is_not(self):
        self.assertFalse(is_human_input(assistant()))


class TestMetrics(unittest.TestCase):
    def test_usage_iterations_not_double_counted(self):
        root = write_dir({"a.jsonl": [assistant(cache_read=1000, cache_creation=100,
                                                out=10)]})
        m, _ = assess(root)
        self.assertEqual(m.cache_read, 1000)
        self.assertEqual(m.cache_creation, 100)
        self.assertEqual(m.output_tokens, 10)
        self.assertAlmostEqual(m.cache_reuse, 10.0)
        shutil.rmtree(root)

    def test_subagent_files_counts_files_not_records(self):
        root = write_dir({
            "a.jsonl": [assistant(sidechain=True), assistant(sidechain=True)],
            "b.jsonl": [assistant(sidechain=True)],
            "c.jsonl": [assistant()],
        })
        m, _ = assess(root)
        self.assertEqual(m.subagent_files, 2)
        shutil.rmtree(root)

    def test_bad_lines_are_counted_not_fatal(self):
        root = write_dir({"a.jsonl": [assistant()]})
        p = next((root / "projects").rglob("a.jsonl"))
        with p.open("a") as fh:
            fh.write("{ not json\n\n")
        m, _ = assess(root)
        self.assertEqual(m.parse_errors, 1)
        self.assertEqual(m.assistant, 1)
        shutil.rmtree(root)

    def test_stats_cache_is_read(self):
        root = write_dir({"a.jsonl": [assistant()]}, stats={"dailyActivity": [
            {"date": "2026-09-10", "messageCount": 100, "sessionCount": 3,
             "toolCallCount": 50},
            {"date": "2026-09-11", "messageCount": 50, "sessionCount": 1,
             "toolCallCount": 20}]})
        m, _ = assess(root)
        self.assertTrue(m.stats_available)
        self.assertEqual(m.stats_days, 2)
        self.assertEqual(m.stats_messages, 150)
        self.assertEqual(m.stats_tool_calls, 70)
        shutil.rmtree(root)

    def test_window_filters_records(self):
        root = write_dir({"a.jsonl": [
            assistant(ts="2026-08-01T00:00:00.000Z"),
            assistant(ts="2026-09-10T00:00:00.000Z")]})
        m = A.scan(root, since=A.parse_date("2026-09-01"))
        self.assertEqual(m.assistant, 1)
        shutil.rmtree(root)

    def test_verification_ratio(self):
        tools = ([("Bash", {"command": "make"})] * 2
                 + [("Bash", {"command": "pytest"})] * 2
                 + [("Bash", {"command": "cat f"})] * 6)
        root = write_dir({"a.jsonl": [assistant(tools=tools)]})
        m, _ = assess(root)
        self.assertEqual(m.bash_total, 10)
        self.assertEqual(m.verification_calls, 4)
        self.assertAlmostEqual(m.verification_ratio, 0.4)
        shutil.rmtree(root)


class TestLevels(unittest.TestCase):
    """Cumulative gates: each level requires the preceding level."""

    @staticmethod
    def _l0():
        return write_dir({"a.jsonl": []})

    @staticmethod
    def _l1():
        # Conversation with almost no tool execution.
        recs = []
        for _ in range(10):
            recs += [user("Explain this code"), assistant()]
        return write_dir({"a.jsonl": recs})

    @staticmethod
    def _l2():
        # Edits directed at nearly every step do not meet the L3 tool/input ratio.
        recs = []
        for _ in range(40):
            recs += [user("Change this section"),
                     assistant(tools=[("Edit", {})]), tool_result(),
                     assistant()]
        return write_dir({"a.jsonl": recs})

    @staticmethod
    def _l3():
        # A long single-agent workflow with no delegation signals.
        recs = []
        for _ in range(20):
            recs.append(user("Fix this bug and make the tests pass"))
            recs.append(assistant(tools=[("Edit", {})]))
            for _ in range(5):
                recs += [assistant(tools=[("Bash", {"command": "pytest"})]),
                         tool_result()]
            recs += [assistant(), assistant()]
        return write_dir({"a.jsonl": recs})

    @staticmethod
    def _l4():
        files = {}
        for day in range(3):
            recs = []
            ts = f"2026-09-{10 + day}T10:00:00Z"
            for _ in range(5):
                recs.append(user("Implement and verify", ts=ts))
                recs.append(assistant(tools=[("Edit", {})], ts=ts))
                for _ in range(12):
                    recs.append(assistant(tools=[("Bash", {"command": "pytest"})], ts=ts))
            for rec in recs:
                rec["sessionId"] = f"session-{day}"
            files[f"main-{day}.jsonl"] = recs
        return write_dir(files)

    def test_l0_no_data(self):
        root = self._l0()
        _, r = assess(root)
        self.assertEqual(r["current"], 0)
        shutil.rmtree(root)

    def test_l1_chat_only(self):
        root = self._l1()
        _, r = assess(root)
        self.assertEqual(r["current"], 1)
        shutil.rmtree(root)

    def test_l2_vibe_coding(self):
        root = self._l2()
        m, r = assess(root)
        self.assertEqual(r["current"], 2, msg=f"tool/human={m.tool_per_human}")
        self.assertEqual(r["status"][3], "NOT VERIFIED")
        shutil.rmtree(root)

    def test_l3_agent_coding(self):
        root = self._l3()
        m, r = assess(root)
        self.assertEqual(r["current"], 3, msg=f"tool/human={m.tool_per_human}")
        self.assertEqual(r["status"][3], "OBSERVED")
        self.assertEqual(r["status"][4], "NOT VERIFIED")
        shutil.rmtree(root)

    def test_l4_repeated_engineering_without_delegation(self):
        root = self._l4()
        m, r = assess(root)
        self.assertGreaterEqual(len(m.engineering_sessions), A.L4_MIN_ENGINEERING_SESSIONS)
        self.assertEqual(r["current"], 4)
        shutil.rmtree(root)

    def test_workflow_and_test_calls_without_edits_are_not_l4(self):
        recs = []
        for _ in range(20):
            recs.append(user("go"))
            for _ in range(12):
                recs += [assistant(tools=[("Bash", {"command": "pytest"})]),
                         tool_result()]
        recs.append(assistant(tools=[("Workflow", {})]))
        root = write_dir({"a.jsonl": recs})
        m, r = assess(root)
        self.assertEqual(m.subagent_files, 0)
        self.assertEqual(m.workflow_calls, 1)
        self.assertEqual(r["current"], 1)
        shutil.rmtree(root)

    def test_l5_requires_evidence(self):
        root = self._l4()
        _, r = assess(root)
        self.assertEqual(r["current"], 4)
        self.assertEqual(len(r["gaps"]), 5)
        shutil.rmtree(root)


class TestRenderPrivacy(unittest.TestCase):
    SECRET_CMD = "grep -rn SUPERSECRETTOKEN /home/someone/private/repo"
    SECRET_PROMPT = "Do not disclose MY_PRIVATE_PROMPT_TEXT"

    def setUp(self):
        self.root = write_dir({"a.jsonl": [
            user(self.SECRET_PROMPT),
            assistant(tools=[("Bash", {"command": self.SECRET_CMD,
                                       "description": "SECRET_DESC"})]),
            tool_result(),
        ]})
        self.m, self.res = assess(self.root)

    def tearDown(self):
        shutil.rmtree(self.root)

    def _outputs(self):
        report = A.build_report(self.m, self.res, None, None)
        return [A.render_report(report), A.render_report(report, markdown=True),
                json.dumps(report)]

    def test_no_secrets_in_any_format(self):
        for out in self._outputs():
            for needle in ("SUPERSECRETTOKEN", "MY_PRIVATE_PROMPT_TEXT",
                           "SECRET_DESC", "/home/someone", "grep -rn"):
                self.assertNotIn(needle, out, msg=needle)

    def test_command_is_still_classified(self):
        self.assertEqual(self.m.bash["search"], 1)

    def test_json_is_valid_and_has_contract_keys(self):
        d = json.loads(self._outputs()[-1])
        for k in ("current_level", "next_target", "long_target", "observed",
                  "levels", "gaps", "stats_cache"):
            self.assertIn(k, d)
        self.assertEqual(d["long_target"], 7)

    def test_zero_count_verification_is_preserved_in_json(self):
        report = A.build_report(self.m, self.res, None, None)
        self.assertEqual(report['observed']['bash']['test'], 0)
        self.assertEqual(report['observed']['verification_calls'], 0)

    def test_text_report_has_spec_sections(self):
        out = A.render_report(A.build_report(self.m, self.res, None, None))
        for token in ("Current Level", "Next Target", "Anthropic", "Observed",
                      "L3 Agent Coding", "L7 Recursive SI"):
            self.assertIn(token, out)


def run_main(argv):
    """Run the CLI, capture report output, and return the exit code."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        rc = A.main(["--source", "claude", "--output", "-"] + argv)
    return rc, buf.getvalue()


class TestCLI(unittest.TestCase):
    def test_main_runs_all_formats(self):
        root = write_dir({"a.jsonl": [user("hi"), assistant()]})
        for fmt in ("text", "md", "json"):
            rc, out = run_main(["--claude-dir", str(root), "--format", fmt])
            self.assertEqual(rc, 0)
            self.assertTrue(out.strip())
        shutil.rmtree(root)

    def test_missing_dir_still_produces_report(self):
        self.assertEqual(run_main(["--claude-dir", "/nope/nothing"])[0], 0)

    def test_days_conflicts_with_since(self):
        self.assertEqual(run_main(["--days", "7", "--since", "2026-09-01"])[0], 2)

    def test_bad_date_exits_2(self):
        self.assertEqual(run_main(["--since", "09/01/2026"])[0], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
