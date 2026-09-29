# Setup and task evidence

## Analyzer only

From a local checkout, without uv or pipx:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cd /absolute/path/to/your-project
agent-level
```

Installing the analyzer does not register hooks or modify workspace instructions.
The new distribution is named `agent-level`. If an environment already contains
`ai-engineering-assessment`, prefer a fresh venv, or uninstall that distribution
**before** installing the new checkout; the two distributions share files.
Uninstalling the old package after installing the new one can remove shared
files; reinstall `agent-level` if that happens.

## Optional task recording workflow

Installing the analyzer is enough to read existing activity. To have agents
register acceptance checks before work and record their results afterward, run
bootstrap from a persistent checkout (bash/zsh on Linux or macOS):

```bash
git clone https://github.com/fwhalbert/agent_level.git
cd agent_level
workspace_dir="/absolute/path/to/your-project"
python3 bootstrap.py --project-dir "$workspace_dir" --venv "$workspace_dir/.venv"
source "$workspace_dir/.venv/bin/activate"
cd "$workspace_dir"
agent-level-assess
```

Bootstrap installs the package, adds an absolute reference to this checkout's
`AGENTS.md` in the workspace's `AGENTS.md` and `CLAUDE.md`, configures session notice
hooks, and ignores `out/agent_level/`. It preserves existing instructions. Without
`--venv`, it selects an existing workspace `venv`, otherwise `.venv`.

Keep the tool checkout available. Rerun bootstrap after moving it or changing the
venv. Activate the venv in each new terminal. Start a new Claude Code or Codex
session and assign an engineering task. Follow [the task evidence workflow](../AGENTS.md).
The notice hook only displays “Auto eval enabled.”; new Codex project hooks require
review and trust in `/hooks` before running. Installation alone does not enable
automatic recording.

Keep `.codex/agent-eval/` and `.claude/agent-eval/` local and ignored by Git.
Captured acceptance output may contain sensitive information. Run the analyzer
again after tasks finish to include the new evidence.

## Existing commands

`agent-level-assess`, `agent_level_assess.py`, `agent-level-record`,
`agent-level-session-notice`, and `python3 assess.py` remain available. Existing
assessment entrypoints retain the default title `AI Engineering Assessment` and
filename `ai-engineering-assessment.html` for compatibility.

Use `--source claude|codex|all`, `--since`, `--until`, `--days`, and
`--format html|txt|md|json|txt+html` to select data and output. `--output -` writes
one format to stdout; progress goes to stderr. `--report-name` overrides the title
and default filename. The analyzer never executes commands found in logs.
