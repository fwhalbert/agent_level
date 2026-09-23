# Automatic daily task evidence

These instructions apply to agents in any workspace that links this file from `AGENTS.md` or `CLAUDE.md`. Record each substantive coding, debugging, or validation task automatically as part of the authorized work. Do not ask the user to run the recorder. This is an agent workflow, not a background hook; the agent must read and execute these instructions.

## Session entry notice

`auto_eval_session_notice.py` is an optional `SessionStart` hook for Claude Code and Codex. On a new session, it looks for an `AGENTS.md` or `CLAUDE.md` reference to `AUTO_EVALUATION.md` in the working directory or its ancestors. It displays “Auto eval enabled.” only when that reference exists. The hook does not start a task or run an evaluation; the agent still follows the workflow below when substantive work begins.

The `dot_ws` workspace has project-local hook settings in `.claude/settings.json` and `.codex/hooks.json`. Codex requires review and trust of a new project hook in `/hooks` before it runs. For another workspace, use the same `SessionStart` command hook configuration and point its command to `/home/albert/codes/tools/agent_level/auto_eval_session_notice.py`.

## Start before work

1. Identify the actual repository, current agent (`codex` or `claude`), and model. Use `unknown` for an unavailable model or harness version; never guess.
2. Define acceptance criteria and a command that checks them before changing code. A successful command proves only those criteria; do not use `true`, an echo, or agent self-report as an acceptance check.
3. Register one daily task with the command below and retain the printed task directory. Put records in the workspace root so workspace and nested-repo reports can both discover them. For `dot_ws`, use `--workspace /home/albert/codes/dot_ws`, even when `--repo` is a nested repository.

```bash
python3 /home/albert/codes/tools/agent_level/agent_level_record.py start \
  --repo /absolute/path/to/repo --workspace /absolute/path/to/workspace \
  --source codex --model ACTUAL_MODEL --harness-version unknown \
  --criteria 'Describe the concrete acceptance checks and their limits' \
  --timeout 300 -- python3 -m unittest discover -s tests -v
```

Choose a command appropriate to the task; the example is not a universal check. Arguments after `--` are an argv list, run in `--repo` without a shell. If a check needs shell setup (including the `dot_ws` Python venv), explicitly use `-- bash -lc 'source venv/bin/activate && ...'`. Only execute commands already authorized by the user task. When no meaningful executable check is available, omit the command and finish as unknown with the reason.

## Finish before the final reply

After implementation, run the registered acceptance check through the recorder; this is the validation run, so a separate duplicate run is unnecessary:

```bash
python3 /home/albert/codes/tools/agent_level/agent_level_record.py finish \
  --task-dir /absolute/path/printed/by/start
```

For unavailable verification, cancellation, blocked hardware, or incomplete work:

```bash
python3 /home/albert/codes/tools/agent_level/agent_level_record.py finish \
  --task-dir /absolute/path/printed/by/start --unknown 'Specific reason verification was not completed'
```

The finish command writes a command log, collector journal, SHA-256-linked grader evidence and outcome, then atomically publishes `results.json`. Exit codes: `0` acceptance passed, `1` acceptance failed, `2` unknown or recording error. Timeout, launch failure, and interruption cannot become a pass. An abruptly stopped task remains running/grading and is counted as unknown; a grading task can be closed with `--unknown` without rerunning its command. Completed tasks are not overwritten; a later acceptance attempt needs a new task, retaining the earlier result.

Records live under `<workspace>/.codex/agent-eval/tasks/<id>/` or `.claude/agent-eval/tasks/<id>/`. Keep them local; do not stage or commit evidence or copy secrets/full conversations into it. The journal records this acceptance run, not the full agent session. Criteria coverage and artifact identity are local evidence, not independent audit or an immutable source snapshot. Do not retroactively invent outcomes for old sessions. If these instructions are first discovered after work began, record only subsequent checks with that boundary stated in the criteria.

If recording fails, continue the authorized task and report the concrete collection failure; never silently claim evidence was saved. Preserve the task directory across turn/context boundaries. Ordinary conversation without a substantive engineering task does not require an eval.

## Read the result

```bash
python3 /home/albert/codes/tools/agent_level/assess.py \
  --project-dir /home/albert/codes/dot_ws
```

The evaluator remains read-only and automatically discovers these daily records. Historical session activity alone does not supply a task outcome.
