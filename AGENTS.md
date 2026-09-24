<!-- agent-level:task-evidence:start -->
# Automatic Task Evidence

These instructions apply to agents in any workspace containing or importing this section in `AGENTS.md` or `CLAUDE.md`. Read and follow the referenced file when a workspace uses an `@` import. Record each substantive coding, debugging, or validation task automatically as part of the authorized work. Do not ask the user to run the recorder. This is an agent workflow, not a background hook; the agent must execute these instructions.

## Session entry notice

`auto_eval_session_notice.py` is an optional `SessionStart` hook for Claude Code and Codex. On a new session, it looks for this task evidence section in `AGENTS.md` or `CLAUDE.md` in the working directory or its ancestors, following standalone `@path/to/file.md` imports. It displays “Auto eval enabled.” only when that section exists. The hook does not start a task or run an evaluation; the agent still follows the workflow below when substantive work begins.

Workspace hook settings live in `.claude/settings.json` and `.codex/hooks.json`. Codex requires review and trust of a new project hook in `/hooks` before it runs. From the tool checkout, `python3 bootstrap.py --project-dir /path/to/workspace` installs the package into the selected venv and adds an absolute `@` reference to this checkout's `AGENTS.md` in the workspace instructions. Existing copied rules are migrated to a reference. Keep the source checkout available; rerun bootstrap after moving it or changing the venv.

Activate the selected venv with `source /path/to/venv/bin/activate` (bash/zsh), then use `agent-level-record`, `agent-level-assess`, and `agent-level-session-notice`. The examples below assume the venv is activated; otherwise use the absolute path to its `bin/` command. Bootstrap defaults to the workspace's existing `venv`, otherwise `.venv`; an explicit `--venv` selects another path, also recorded in the notice hook command. Bootstrap prints the exact activation command when setup completes. Installing the package alone does not register hooks or make the agent follow this workflow; keep the reference in the workspace instructions.

## Start before work

1. Identify the actual repository, current agent (`codex` or `claude`), model, and reasoning effort. Record model and effort separately (for example, `GPT-6-Sol` with `xhigh`, or `Opus 5.5 (1M context)` with `high`). Use `unknown` for any unavailable value or harness version; never guess.
2. Define acceptance criteria and a command that checks them before changing code. A successful command proves only those criteria; do not use `true`, an echo, or agent self-report as an acceptance check.
3. Register one daily task with the command below and retain the printed task directory. Put records in the actual workspace root so workspace and nested-repo reports can both discover them, even when `--repo` is a nested repository.

```bash
agent-level-record start \
  --repo /absolute/path/to/repo --workspace /absolute/path/to/workspace \
  --source codex --model ACTUAL_MODEL --reasoning-effort ACTUAL_EFFORT --harness-version unknown \
  --criteria 'Describe the concrete acceptance checks and their limits' \
  --timeout 300 -- python3 -m unittest discover -s tests -v
```

Choose a command appropriate to the task; the example is not a universal check. Arguments after `--` are an argv list, run in `--repo` without a shell. If a check needs shell setup (such as activating the project's Python venv), explicitly use `-- bash -lc 'source /path/to/venv/bin/activate && ...'`. Only execute commands already authorized by the user task. When no meaningful executable check is available, omit the command and finish as unknown with the reason.

For older records with no `reasoning_effort` field, reports use a documented official model default where one is known; this is an assumed setting, not proof of the historical runtime configuration. An explicit `unknown` stays unknown. Filter task results with `agent-level-assess --model MODEL --effort LEVEL`; these filters do not change the L0–L7 historical-log assessment.

## Finish before the final reply

After implementation, run the registered acceptance check through the recorder; this is the validation run, so a separate duplicate run is unnecessary:

```bash
agent-level-record finish \
  --task-dir /absolute/path/printed/by/start
```

For unavailable verification, cancellation, blocked hardware, or incomplete work:

```bash
agent-level-record finish \
  --task-dir /absolute/path/printed/by/start --unknown 'Specific reason verification was not completed'
```

The finish command writes a command log, collector journal, SHA-256-linked grader evidence and outcome, then atomically publishes `results.json`. Captured output is bounded to 16 MiB; exceeding the limit terminates the acceptance process group and records unknown. Local verification checks the journal's output hash and agreement with the grader verdict. Exit codes: `0` acceptance passed, `1` acceptance failed, `2` unknown or recording error. Timeout, launch failure, and interruption cannot become a pass. An abruptly stopped task remains running/grading and is counted as unknown; a grading task can be closed with `--unknown` without rerunning its command. Completed tasks are not overwritten; a later acceptance attempt needs a new task, retaining the earlier result.

Records live under `<workspace>/.codex/agent-eval/tasks/<id>/` or `.claude/agent-eval/tasks/<id>/`. Keep them local; do not stage or commit evidence or copy secrets/full conversations into it. The journal records this acceptance run, not the full agent session. Criteria coverage and artifact identity are local evidence, not independent audit or an immutable source snapshot. Do not retroactively invent outcomes for old sessions. If these instructions are first discovered after work began, record only subsequent checks with that boundary stated in the criteria.

If recording fails, continue the authorized task and report the concrete collection failure; never silently claim evidence was saved. Preserve the task directory across turn/context boundaries. Ordinary conversation without a substantive engineering task does not require an eval.

## Read the result

```bash
cd /path/to/workspace
agent-level-assess
```

The evaluator remains read-only and automatically discovers these daily records. Historical session activity alone does not supply a task outcome.
<!-- agent-level:task-evidence:end -->
