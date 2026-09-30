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
one command from a source checkout (bash/zsh on Linux or macOS):

```bash
./agent-level setup --project-dir /absolute/path/to/your-project
```

The checkout's `agent-level` executable works before package installation.
Setup creates or reuses the selected venv, installs the package when needed,
then adds an absolute reference to the installed task evidence workflow in
the workspace's `AGENTS.md` and `CLAUDE.md`, configures session notice
hooks, and preserves existing instructions. It does not create, read or modify
the target project's `.gitignore`; the project manages its own ignore rules. Without
`--venv`, it uses the venv running the command. When run outside a venv from a checkout,
it selects an existing workspace `venv`, otherwise `.venv`, and installs there.

It prints an absolute report command with `--project-dir`, so you can run it from
any directory without activating a venv. The workspace's `AGENTS.md` also contains
the absolute recorder and report commands; agents can follow the recording workflow
without relying on shell activation or PATH changes.

If the package is already installed, use `agent-level setup` in your project,
or invoke `/path/to/venv/bin/agent-level setup --project-dir /path/to/workspace`
directly. Use `--project-dir /path/to/workspace` to select another workspace. From a source
checkout, `--venv /path/to/venv` installs into a different environment. With a wheel
installation, install Agent Level in the desired venv and run its setup command
there. Wheels include the recording workflow and do not need the source checkout.

Keep the tool installation available. Rerun setup after moving it or changing the
venv. Start a new Claude Code or Codex
session and assign an engineering task. Follow [the task evidence workflow](../AGENTS.md).
The notice hook only displays “Auto eval enabled.”; new Codex project hooks require
review and trust in `/hooks` before running. Installation alone does not enable
automatic recording.

Keep `.codex/agent_level/` and `.claude/agent_level/` local and ignored by Git.
The recorder and analyzer use only `agent_level/tasks/`. For existing records,
manually rename the data directory to `agent_level` when the destination is absent,
preserving the evidence files. Use the updated task path with `record finish`.
Captured acceptance output may contain sensitive information. Run the analyzer
again after tasks finish to include the new evidence.

## Existing commands

`./agent-level` runs the public CLI from a checkout without prior installation;
`agent-level setup` is the installed recording setup command. The source-only
`bootstrap.py` remains a compatibility entrypoint for existing automation.

`agent-level-assess`, `agent_level_assess.py`, `agent-level-record`,
`agent-level-session-notice`, and `python3 assess.py` remain available. Existing
assessment entrypoints retain the default title `AI Engineering Assessment` and
filename `ai-engineering-assessment.html` for compatibility.

Use `--source claude|codex|all`, `--since`, `--until`, `--days`, and
`--format html|txt|md|json|txt+html` to select data and output. `--output -` writes
one format to stdout; progress goes to stderr. `--report-name` overrides the title
and default filename. The analyzer never executes commands found in logs.
