# AI Engineering Assessment

[English](README.md) | [简体中文](README.zh-CN.md)

**An open-source framework for empirical evaluation of AI-assisted software engineering.** Using local Claude Code and Codex session logs and task acceptance evidence, it examines AI agents in real engineering workflows across three dimensions: human–AI collaboration, task completion reliability, and the effects of workflow changes.

The project turns engineering activity into traceable assessment results, helping developers, teams, and researchers identify the limits of automation, verify task delivery, and compare changes to prompts, tools, and collaboration workflows on fixed task suites. Local data processing and offline reports support continuous improvement and empirical research in AI-assisted engineering.

## What it does

- **Review your workflow:** estimate an L0–L7 candidate level, explain the evidence, and show missing requirements.
- **Check task outcomes:** summarize successful, failed, unknown, and unrun tasks from registered acceptance checks.
- **Compare changes:** examine before/after task results for versioned prompts, tools, or workflows on a fixed task suite.
- **Explore usage:** view daily token usage, model shares, and cache usage, separately for Claude Code, Codex, or both.
- **Keep reports local:** generate an offline English/中文 HTML report, or export text, Markdown, and JSON. Reports contain aggregates, not raw conversations or source code.

Requires **Python 3.10+**; no third-party runtime dependencies. Existing logs are enough for a first workflow report. Task acceptance statistics require task records.

## Supported methods and standards

There is no unified industry standard behind these scores. The current implementation supports:

| Method / protocol | What it answers | Current support |
|---|---|---|
| Project-defined L0–L7 ruleset 1.0 | How is engineering work shared between humans and AI? | Default L0; log candidates for L1–L4; reference definitions for L5–L7 |
| Anthropic-style agent evaluation | Did tasks meet explicit acceptance criteria, and how repeatable are the results? | Daily acceptance outcomes; pass@1, pass@k, and pass^k for complete controlled trial groups |
| Local task result protocol 1.0 / 1.1 | How can task evidence be recorded and imported? | JSON import; 1.1 adds daily task records and optional improvement comparisons |
| Project-defined improvement comparison | Did a workflow change improve autonomous task acceptance? | Paired before/after evidence on the same frozen tasks; regressions and evidence status |

The Anthropic method is applied to both Claude Code and Codex evidence. Anthropic does **not** define this project's L0–L7 levels or certify its results. OpenAI evaluation guidance and research such as SWE-bench and METR are references, not additional implemented scoring standards. See [References](#references).

## Quick start

The commands below use **bash/zsh on Linux or macOS**, with Git and Python 3.10+ installed. Use the same terminal for all steps. Installation may need internet access to obtain Python build tools.

Clone the tool and replace `workspace_dir` with the absolute path of the project you want to assess:

```bash
git clone https://github.com/fwhalbert/agent_level.git
cd agent_level
workspace_dir="/absolute/path/to/your-project"
python3 bootstrap.py --project-dir "$workspace_dir" --venv "$workspace_dir/.venv"
source "$workspace_dir/.venv/bin/activate"
cd "$workspace_dir"
agent-level-assess
```

Bootstrap installs the commands, links task recording instructions in `AGENTS.md` and `CLAUDE.md`, and configures session notice hooks. It preserves existing project instructions and adds the report directory to `.gitignore`.

Open the printed `file://` link in your browser. The offline report supports English/中文 and defaults to `out/agent_level/YYYY-MM-DD/ai-engineering-assessment.html`. Without matching logs, the level defaults to L0; task outcome statistics require acceptance records.

Start a new Claude Code or Codex session in the project and give it an engineering task. The agent follows the [recording workflow](AGENTS.md) to register acceptance criteria before work and record the check afterward. The hook only displays “Auto eval enabled.”; Codex may require review and trust in `/hooks`.

Run `agent-level-assess` again after tasks finish. Activate the venv in each new terminal. Keep the tool checkout available and rerun bootstrap if you move it or change the venv. For command options, run `agent-level-assess --help`.

## Level assessment

L0–L7 describes the division of engineering work between humans and AI. A higher number represents a different degree of delegation and system capability; choose the workflow that fits your work.

| Level | Name | What it looks like | Main human role |
|---|---|---|---|
| L0 | Manual Engineering | Humans implement and verify; AI is at most a reference | Developer |
| L1 | AI-assisted Coding | AI explains, suggests, or generates snippets; humans integrate them | Developer |
| L2 | Interactive AI Coding | AI edits files directly; humans frequently choose the next step | Step decision maker |
| L3 | Agent Coding | Given a task, an agent edits and attempts verification | Task initiator |
| L4 | Agent-first Engineering | The edit-and-verify workflow repeats across sessions and days | Supervisor |
| L5 | Autonomous Engineering | An agent picks up tasks, delivers changes, repairs CI, and tracks outcomes | Specification and acceptance owner |
| L6 | Self-improving Engineering System | Results drive changes to prompts, tools, or workflows, with evaluation and rollback | Improvement and governance owner |
| L7 | Governed Recursive Self-Improvement | A system researches, builds, evaluates, and deploys a next-generation system under human governance | Research and governance owner |

**How to read the result:** `DEFAULT` means L0 is achieved by default, without requiring logs or human confirmation. `OBSERVED` means the available log behavior supports a candidate level, not that tasks passed. `NOT VERIFIED` means the required behavior is not established; L5–L7 remain reference definitions without automatic assessment. L0 remains achieved at higher levels; L7 is an optional research direction.

See [level rules and log observation limits](docs/AGENT_LEVEL_L0-L7.md) for thresholds and evidence requirements.

## References

Start with the project guides:

- [L0–L7 definitions and observation rules](docs/AGENT_LEVEL_L0-L7.md): level meanings, thresholds, and evidence states.
- [Anthropic-style evaluation and JSON protocol](docs/ANTHROPIC.md): task outcomes, graders, and repeated-trial statistics.
- [Before/after improvement evaluation](docs/IMPROVEMENT_EVALUATION.md): controlled comparisons and evidence requirements.
- [OpenAI evaluation guidance and project scope](docs/OPENAI.md): how the guidance maps to current capabilities and gaps.
- [Sources and references](docs/REFERENCES.md): primary sources from Anthropic, OpenAI, SWE-bench, METR, SPACE, DORA, DeepMind, and NIST, with their relevance and limits.

These sources inform the methods; they do not validate this project's level thresholds or imply endorsement.
