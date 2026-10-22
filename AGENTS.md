# Repository version policy

This section applies only when modifying the `agent_level` tool itself, not to workspaces importing the task evidence workflow below.

Keep the project at **v1**: package and CLI version `1.0.0`, L0–L7 ruleset version `1.0`. Do not bump these versions unless the user explicitly requests an upgrade. Keep code, package metadata, documentation, tests, and release commit messages consistent with this policy.

<!-- agent-level:task-evidence:start -->
# Automatic Task Evidence

These instructions apply when global or workspace `AGENTS.md` or `CLAUDE.md` contains or references this section. Read and follow the referenced file when instructions use an `@` import. Record each substantive coding, debugging, or validation task automatically as part of the authorized work. Do not ask the user to run the recorder. This is an agent workflow, not a background hook; the agent must execute these instructions.

## Commands

Setup is documented in [docs/SETUP.md](docs/SETUP.md). Use the checkout containing this referenced `AGENTS.md` to locate commands. Replace `/absolute/path/to/agent_level` in the examples below with that checkout's actual absolute path; quote paths containing spaces. Call `python3 /absolute/path/to/agent_level/agent_level_record.py` for recording and `python3 /absolute/path/to/agent_level/agent-level` for reports. Do not rely on PATH, an activated venv, or a per-project installation. Python 3.9+ is required.

## Start before work

1. Identify the actual repository, current agent (`codex` or `claude`), model, and reasoning effort. Record model and effort separately (for example, `GPT-6-Sol` with `xhigh`, or `Opus 5.5 (1M context)` with `high`). Use `unknown` for any unavailable value or harness version; never guess.
2. Define acceptance criteria and a command that checks them before changing code. A successful command proves only those criteria; do not use `true`, an echo, or agent self-report as an acceptance check.
3. Register one daily task with the command below and retain the printed task directory. Put records in the actual workspace root so workspace and nested-repo reports can both discover them, even when `--repo` is a nested repository.

```bash
python3 /absolute/path/to/agent_level/agent_level_record.py start \
  --repo /absolute/path/to/repo --workspace /absolute/path/to/workspace \
  --source codex --model ACTUAL_MODEL --reasoning-effort ACTUAL_EFFORT --harness-version unknown \
  --criteria 'Describe the concrete acceptance checks and their limits' \
  --timeout 300 -- python3 -m unittest discover -s tests -v
```

Choose a command appropriate to the task; the example is not a universal check. Arguments after `--` are an argv list, run in `--repo` without a shell. If a check needs shell setup (such as activating the project's Python venv), explicitly use `-- bash -lc 'source /path/to/venv/bin/activate && ...'`. Only execute commands already authorized by the user task. When no meaningful executable check is available, omit the command and finish as unknown with the reason.

When known, record standard provenance with `--criteria-version`, `--criteria-author`, `--criteria-review-source`, `--criteria-reviewer` and `--criteria-review-ref`; otherwise retain `unknown`. If the current agent writes the criteria, record its known identity as the author and use `--criteria-review-source self`; this does not establish human or independent review. Add explicit `--session-id` values only when available. New registrations freeze the acceptance plan locally; do not edit it to make acceptance pass. Existing authorized templates do not require asking for approval again. Human reviews must come from actual human input, recorded separately with `python3 /absolute/path/to/agent_level/agent_level_record.py review`; never invent a human verdict or intervention count. See [workflow metrics and review](docs/WORKFLOW_METRICS.md).

## Finish before the final reply

For both Codex and Claude, after the final code or test edit and before the final reply, run the registered acceptance check through the recorder and inspect its result. An earlier passing check does not validate a later edit. This is the validation run, so a separate duplicate run is unnecessary. If further edits follow a completed acceptance attempt, register a new task before those edits and finish it afterward; retain the earlier result:

```bash
python3 /absolute/path/to/agent_level/agent_level_record.py finish \
  --task-dir /absolute/path/printed/by/start
```

For unavailable verification, cancellation, blocked hardware, or incomplete work:

```bash
python3 /absolute/path/to/agent_level/agent_level_record.py finish \
  --task-dir /absolute/path/printed/by/start --unknown 'Specific reason verification was not completed'
```

Use `--unknown` only when verification cannot be completed, not to skip an available check. Inspect the local journal and command log before diagnosing the cause. Use `--reason timeout`, `interruption`, `launch_failure`, `output_limit`, `evidence_missing` or `verification_unavailable` when supported by the evidence. Without an explicit reason, closing an interrupted `grading` attempt records `interruption`; other skipped attempts record `verification_unavailable`. That label alone does not establish a grader or environment defect. State any verification limitation in the final reply.

Finish writes the command log, journal, grader evidence and outcome, then publishes `results.json`; output over 16 MiB stops the check and records unknown. Exit codes: `0` acceptance passed, `1` acceptance failed, `2` unknown or recording error. Timeout, launch failure, and interruption cannot become a pass. An abruptly stopped task remains running/grading and is counted as unknown; a grading task can be closed with `--unknown` without rerunning its command. Completed tasks are not overwritten; a later acceptance attempt needs a new task, retaining the earlier result.

Records live under `<workspace>/.codex/agent_level/tasks/<id>/` or `.claude/agent_level/tasks/<id>/`. Keep them local; do not stage or commit evidence or copy secrets/full conversations into it. The journal records this acceptance run, not the full agent session. Criteria coverage and artifact identity are local evidence, not independent audit or an immutable source snapshot. Do not retroactively invent outcomes for old sessions. If these instructions are first discovered after work began, record only subsequent checks with that boundary stated in the criteria.

If recording fails, continue the authorized task and report the concrete collection failure; never silently claim evidence was saved. Preserve the task directory across turn/context boundaries. Ordinary conversation without a substantive engineering task does not require an eval.

## Read the result

```bash
python3 /absolute/path/to/agent_level/agent-level --project-dir /path/to/workspace
```

The evaluator remains read-only and automatically discovers these daily records. Historical session activity alone does not supply a task outcome.
<!-- agent-level:task-evidence:end -->
