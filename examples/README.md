# Synthetic example

The fabricated logs in `sample-data/` exercise the real Codex parser and report
renderer: three sessions across two UTC days produce L4 / OBSERVED. They contain
no personal data or verified task outcomes; fixture commands are never executed.
L5–L7 remain unverified.

Generate the report from the checkout:

```bash
python3 examples/generate_report.py
```

Open `out/agent_level/example/agent-level.html` in a browser. Markdown and JSON
are written alongside it; use `--output-dir` to choose another directory.
Generated reports are ignored by Git.

The generator reads only `examples/sample-data/codex`, uses a fixed report time,
and writes deterministic output. It never scans home directories. The same
fixtures are used by the CLI and report tests.
