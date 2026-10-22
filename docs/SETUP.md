# Setup and task evidence

## Global Codex configuration

Requires Git and Python 3.9+ on Linux or macOS. From the source checkout:

```bash
./agent-level setup
```

Setup adds this block to `~/.codex/AGENTS.md`, using the checkout's actual path:

```markdown
## agent_level: automatic task evidence

Read and follow the task evidence workflow in:
@/absolute/path/to/agent_level/AGENTS.md
```

Existing personal rules are preserved. Repeating setup updates the reference
without duplicating it. `CODEX_HOME` changes the default configuration directory;
`./agent-level setup --codex-home /path/to/codex-home` overrides it explicitly.
Start a new Codex session after setup. The agent must read and follow the
referenced workflow; the reference does not run an evaluation by itself.

Setup does not install packages, create venvs, register hooks, or write project
instructions. It prints a command that runs this checkout directly. Keep the
checkout available and rerun setup after moving it. macOS Python 3.9 supplied by
Apple's Command Line Tools is supported. Quote paths containing spaces.

For Claude Code, add the same reference to `~/.claude/CLAUDE.md` manually.
Codex setup does not change Claude configuration. The optional session notice
script only checks workspace instructions; it is not needed for global recording.

## Direct source commands

Replace the checkout and workspace paths below with your actual paths. No
installation, environment activation, or PATH change is required:

```bash
python3 /absolute/path/to/agent_level/agent-level --project-dir "/path/to/your project"
python3 /absolute/path/to/agent_level/agent_level_record.py --help
```

The analyzer can be used without setup. It reads existing activity without
registering hooks or modifying instructions. With no `--project-dir`, the public
CLI assesses the current directory. The recording commands are documented in
[the task evidence workflow](../AGENTS.md).

Records stay under the evaluated workspace's `.codex/agent_level/tasks/` or
`.claude/agent_level/tasks/`, not the tool checkout or global configuration directory.
Keep these evidence directories local and ignored by Git. Setup does not change
`.gitignore`. Captured acceptance output may contain sensitive information.

## Migration from project installation

Run the global setup command once. `setup --project-dir` and `setup --venv` are no
longer supported. The `--project-dir` option remains available for analysis and
report generation.

Setup leaves existing project files and venvs untouched. Remove only old
Agent Level instruction blocks and notice hook entries that you no longer need;
preserve other project rules and hooks. Keep existing task records. Do not delete
a shared project venv just to migrate Agent Level. Use source commands for future
recording and reports, including `finish --task-dir` for existing task directories.

## Existing commands

`./agent-level` and `python3 bootstrap.py` run from a source checkout. Global setup
requires the checkout; a standalone wheel cannot provide a reference to its source
`AGENTS.md`.

Previously installed `agent-level-assess`, `agent_level_assess.py`,
`agent-level-record`, and `agent-level-session-notice` remain available.
`python3 /absolute/path/to/agent_level/assess.py` runs the legacy analyzer directly.
Legacy assessment entrypoints retain the title `AI Engineering Assessment` and
filename `ai-engineering-assessment.html` for compatibility.

Use `--source claude|codex|all`, `--since`, `--until`, `--days`, and
`--format html|txt|md|json|txt+html` to select data and output. `--output -` writes
one format to stdout; progress goes to stderr. `--report-name` overrides the title
and default filename. The analyzer never executes commands found in logs.
