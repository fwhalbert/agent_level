<!-- agent-level:task-evidence:start -->
# Automatic Task Evidence

These instructions apply to agents in any workspace containing or importing this section in `AGENTS.md` or `CLAUDE.md`. Read and follow the referenced file when a workspace uses an `@` import. Record each substantive coding, debugging, or validation task automatically as part of the authorized work. Do not ask the user to run the recorder. This is an agent workflow, not a background hook; the agent must execute these instructions.

## Session entry notice

`auto_eval_session_notice.py` is an optional `SessionStart` hook for Claude Code and Codex. On a new session, it looks for this task evidence section in `AGENTS.md` or `CLAUDE.md` in the working directory or its ancestors, following standalone `@path/to/file.md` imports. It displays “Auto eval enabled.” only when that section exists. The hook does not start a task or run an evaluation; the agent still follows the workflow below when substantive work begins.

Workspace hook settings live in `.claude/settings.json` and `.codex/hooks.json`. Codex requires review and trust of a new project hook in `/hooks` before it runs. With Agent Level installed, `agent-level setup --project-dir /path/to/workspace` adds an absolute `@` reference to the installed workflow in the workspace instructions and configures notice hooks. Existing copied rules are migrated to a reference. Keep the installation available; rerun setup after moving it or changing the venv.

From a source checkout, `./agent-level setup --project-dir /path/to/workspace` installs and configures the workflow in one command. Setup prints an absolute report command without adding command information to the workspace instructions. The examples below assume the commands are on PATH; otherwise use the executables in the selected venv's `bin` directory without activating it. Setup defaults to the venv running the command, otherwise the workspace's existing `venv` or `.venv` when run from a checkout. An explicit `--venv` selects another path from a checkout, also recorded in the notice hook command. Installing the package alone does not register hooks or make the agent follow this workflow; keep the reference in the workspace instructions.

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

When known, record standard provenance with `--criteria-version`, `--criteria-author`, `--criteria-review-source`, `--criteria-reviewer` and `--criteria-review-ref`; otherwise retain `unknown`. If the current agent writes the criteria, record its known identity as the author and use `--criteria-review-source self`; this does not establish human or independent review. Add explicit `--session-id` values only when available. New registrations freeze the acceptance plan locally; do not edit it to make acceptance pass. Existing authorized templates do not require asking for approval again. Human reviews must come from actual human input, recorded separately with `agent-level-record review`; never invent a human verdict or intervention count. See [workflow metrics and review](docs/WORKFLOW_METRICS.md).

For older records with no `reasoning_effort` field, reports use a documented official model default where one is known; this is an assumed setting, not proof of the historical runtime configuration. An explicit `unknown` stays unknown. Filter task results with `agent-level-assess --model MODEL --effort LEVEL`; these filters do not change the L0–L7 historical-log assessment.

## Finish before the final reply

For both Codex and Claude, after the final code or test edit and before the final reply, run the registered acceptance check through the recorder and inspect its result. An earlier passing check does not validate a later edit. This is the validation run, so a separate duplicate run is unnecessary. If further edits follow a completed acceptance attempt, register a new task before those edits and finish it afterward; retain the earlier result:

```bash
agent-level-record finish \
  --task-dir /absolute/path/printed/by/start
```

For unavailable verification, cancellation, blocked hardware, or incomplete work:

```bash
agent-level-record finish \
  --task-dir /absolute/path/printed/by/start --unknown 'Specific reason verification was not completed'
```

Use `--unknown` only when verification cannot be completed, not to skip an available check. Inspect the local journal and command log before diagnosing the cause. Use `--reason timeout`, `interruption`, `launch_failure`, `output_limit`, `evidence_missing` or `verification_unavailable` when supported by the evidence. Without an explicit reason, closing an interrupted `grading` attempt records `interruption`; other skipped attempts record `verification_unavailable`. That label alone does not establish a grader or environment defect. State any verification limitation in the final reply.

The finish command writes a command log, collector journal, SHA-256-linked grader evidence and outcome, then atomically publishes `results.json`. Captured output is bounded to 16 MiB; exceeding the limit terminates the acceptance process group and records unknown. Local verification checks the journal's output hash and agreement with the grader verdict. Exit codes: `0` acceptance passed, `1` acceptance failed, `2` unknown or recording error. Timeout, launch failure, and interruption cannot become a pass. An abruptly stopped task remains running/grading and is counted as unknown; a grading task can be closed with `--unknown` without rerunning its command. Completed tasks are not overwritten; a later acceptance attempt needs a new task, retaining the earlier result.

Records live under `<workspace>/.codex/agent_level/tasks/<id>/` or `.claude/agent_level/tasks/<id>/`. Keep them local; do not stage or commit evidence or copy secrets/full conversations into it. The journal records this acceptance run, not the full agent session. Criteria coverage and artifact identity are local evidence, not independent audit or an immutable source snapshot. Do not retroactively invent outcomes for old sessions. If these instructions are first discovered after work began, record only subsequent checks with that boundary stated in the criteria.

If recording fails, continue the authorized task and report the concrete collection failure; never silently claim evidence was saved. Preserve the task directory across turn/context boundaries. Ordinary conversation without a substantive engineering task does not require an eval.

## Read the result

```bash
cd /path/to/workspace
agent-level-assess
```

The evaluator remains read-only and automatically discovers these daily records. Historical session activity alone does not supply a task outcome.
<!-- agent-level:task-evidence:end -->
