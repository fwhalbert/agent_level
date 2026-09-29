# Agent Level

[![Tests](https://github.com/fwhalbert/agent_level/actions/workflows/test.yml/badge.svg)](https://github.com/fwhalbert/agent_level/actions/workflows/test.yml)

[English](README.md) | [简体中文](README.zh-CN.md)

Agent Level analyzes local **Claude Code and Codex** activity and task evidence
to show how engineering work is shared between humans and agents.

## What it does

- **Assess your workflow:** see an L0–L7 candidate level, supporting evidence, and gaps.
- **Track task results:** summarize acceptance outcomes from registered checks.
- **Compare improvements:** compare workflow changes on the same frozen tasks.
- **Explore usage:** view daily tokens, model shares, and cache usage.

Reports support English/中文 offline HTML, text, Markdown, and JSON.
They contain aggregates, not raw conversations or source code.

**Local analysis · No source code upload · Evidence-based · English / 中文 reports**

![L0–L7: human control to system autonomy](docs/assets/agent-level.svg)

## Quick start

Requires Git and Python 3.10+; no third-party runtime dependencies.
Run these commands in bash/zsh on Linux or macOS, replacing `workspace_dir`
with the absolute path of the project you want to assess:

```bash
git clone https://github.com/fwhalbert/agent_level.git
cd agent_level
workspace_dir="/absolute/path/to/your-project"
python3 bootstrap.py --project-dir "$workspace_dir" --venv "$workspace_dir/.venv"
source "$workspace_dir/.venv/bin/activate"
cd "$workspace_dir"
agent-level
```

Bootstrap installs the commands, links task recording instructions in
`AGENTS.md` and `CLAUDE.md`, and configures session notice hooks.
Open the printed `file://` link; the default report is
`out/agent_level/YYYY-MM-DD/agent-level.html`.

Start a new Claude Code or Codex session and assign an engineering task.
The agent records acceptance checks and results through the [recording workflow](AGENTS.md).
The hook only displays “Auto eval enabled.”; new Codex hooks require trust in `/hooks`.
Run `agent-level` again after tasks finish to update the report.

Activate the venv in each new terminal. Keep the tool checkout available;
rerun bootstrap after moving it or changing the venv.
For analyzer-only installation and more options, see [setup](docs/SETUP.md)
or run `agent-level --help`.

## L0–L7 framework

| Level | Engineering workflow | Human role |
|---|---|---|
| L0 — Manual | Human writes and verifies | Developer |
| L1 — Assisted | AI suggests; human integrates | Developer |
| L2 — Interactive | AI edits; human drives steps | Step decision maker |
| L3 — Agent | Human assigns a task; agent edits and attempts verification | Task initiator |
| L4 — Agent-first | Edit/verify workflow repeats across sessions and days | Supervisor |
| L5 — Autonomous | Agents pick up tasks, deliver changes, repair CI, track outcomes | Specification and acceptance owner |
| L6 — Self-improving | System improves prompts, tools and workflows with evaluation and rollback | Improvement and governance owner |
| L7 — Recursive | System develops successive systems under human governance | Research and governance owner |

`DEFAULT` is the L0 baseline, including when no logs match. `OBSERVED` means
logs support an L1–L4 candidate, not task success. L5–L7 remain `NOT VERIFIED`
reference definitions. Task acceptance results are assessed separately.

The project-defined ruleset **1.0** describes workflow autonomy, not developer
ability or model intelligence. It is not an industry standard.
[Full definitions and thresholds](docs/AGENT_LEVEL_L0-L7.md).

## References

- [Setup and task recording](docs/SETUP.md)
- [Task evaluation and JSON protocol](docs/ANTHROPIC.md)
- [Before/after improvement evaluation](docs/IMPROVEMENT_EVALUATION.md)
- [OpenAI guidance and implementation scope](docs/OPENAI.md)
- [Methods, primary sources, and limitations](docs/REFERENCES.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)
