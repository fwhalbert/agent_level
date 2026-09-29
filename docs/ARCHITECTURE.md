# Architecture

Agent Level uses the Python standard library at runtime. It separates behavioral
observations, acceptance outcomes, and controlled comparisons.

```text
Claude Code / Codex local JSONL
  → assessment/logs.py: parse, filter, deduplicate, aggregate
  → assess.py evaluate(): project-defined L0–L4 observations

Registered checks / explicit task JSON
  → agent_level_record.py: registration and acceptance execution
  → assessment/collection.py + evidence.py: discovery and local integrity checks
  → assessment/anthropic.py: task outcomes and controlled repeat statistics
  → assessment/improvement.py: frozen-task before/after comparisons

Aggregate report dictionaries
  → assess.py: text, Markdown, JSON
  → assessment/web.py + web_i18n.py + web_usage.py: offline bilingual HTML
  → assessment/guidance.py: optional experiments based on the existing next target
```

## Entrypoints and boundaries

`assessment/cli.py` dispatches `agent-level` / `assess` to the existing analyzer,
`record` to the recorder, and `compare` to the analyzer with its existing comparison
HTML view selected. Legacy entrypoints retain their defaults. The new CLI changes
branding and presentation, not assessment thresholds or evidence protocols.

Installed commands and `python assess.py` scope logs to the current project by
default. Explicit `--project-dir` selects another existing directory. Explicit
`--eval-results` is a separate import flow and cannot be combined with project
filtering. Progress goes to stderr; `-o -` leaves stdout suitable for report data.

The analyzer reads data only; it never executes logged commands or imported
artifacts. Only `record finish` runs a pre-registered acceptance command. The
recorder binds command output, grader evidence and artifact identity with hashes,
and atomically publishes `results.json`. It does not record the full agent session
or independently establish that criteria cover all requirements.

## Assessment invariants

- L0 is `DEFAULT`; absence of logs does not prove absence of AI work.
- L1–L4 are `OBSERVED` candidates. Edit/verify chains require ordered timestamps in
  the same session, source and selected period. Test calls are attempts.
- L5–L7 remain `NOT VERIFIED`. Acceptance and improvement evidence never promote levels.
- Combined reports add counts, union dates and recalculate ratios; they do not
  join edit/verify chains across sources.
- Unknown, interrupted, and unrun acceptance outcomes remain explicit.
- Gap presentation reuses `gaps` and `next_target`. Experiments neither modify
  report evidence nor add a new score or JSON protocol.

Reports exclude raw prompts, source and command content. User-supplied labels and
aggregate dates can still be sensitive. HTML contains inline CSS/JavaScript and
an embedded aggregate JSON download; no remote resources are loaded. Source links
navigate externally only when opened by the reader.

## Validation

`python -m unittest discover -v` covers parser behavior, source isolation, evidence
integrity, missing-data semantics, offline rendering and CLI behavior. Supply
`AGENT_LEVEL_TEST_WHEELHOUSE` for installation tests; see [contributing](../CONTRIBUTING.md).
`examples/generate_report.py` renders fixed synthetic inputs without scanning a home
directory. See [level definitions](AGENT_LEVEL_L0-L7.md) for exact gates and limits.
