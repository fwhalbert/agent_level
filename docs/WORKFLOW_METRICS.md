# Workflow metrics and review

Package and CLI version remain `1.0.0`; the heuristic ruleset remains `1.0`.
These additions do not change the L0–L7 gates or establish independent audit.

## Verification and trace coverage

JSON reports expose `verification_coverage` and `tool_observability`; HTML,
text and Markdown show the same observations.

- `edited_sessions` counts sessions with visible edit calls in the selected scope.
- `final_edit_verified_sessions` requires a recognized build/test invocation after
  the last observed edit in the same source and session. `edit → test → edit`
  retains the older engineering-session signal but has no final-edit coverage.
- `final_edit_verification_coverage` divides these sessions by visible edited
  sessions. It is null when that denominator is empty.
- Passed, failed and unknown final results describe the latest recognized
  verification invocation after the last observed edit. Missing ordering or
  missing returns remain unknown. Build and test attempts are also shown separately.

The parser cannot prove that a check covers the changed code or that the task was
accepted. It does not bind verification to a source snapshot. Date and project
filters restrict the observations; changes outside the selected logs remain unknown.

Codex session records, supported public JSONL events and explicit nested tool
events are read as data. Logged JavaScript is never evaluated. An orchestration
call is fully expanded only when an explicit complete trace is available; partial
nested events do not erase its visibility gap. Expansion coverage measures observed
orchestration calls, not the fraction of all real tools successfully captured.
Zero recognized verification calls with opaque orchestration does not mean no
verification took place.

The public `codex exec --json` stream normally has no per-event timestamps or
project cwd. Such events can supply call counts and explicit returns, but final
edit chronology remains unknown. Project filtering requires a recorded cwd;
date filtering requires timestamps. Capture these as structured metadata when
available instead of assigning the file's modification time to its events.
Supported nested output is an explicit `nested_tool_calls` array with call IDs,
tool names, inputs, timestamps and optional returns; only
`nested_tool_calls_complete: true` claims a complete expansion.

## Token roles

`model_usage.models` and `daily` retain the existing model breakdown. `roles` and
`daily_roles` split usage into `executor`, `auto_review`, `subagent` and `unknown`
from recorded metadata. Missing role information is not inferred from a model name.

Input includes cache read and creation tokens. Reports show uncached input, cache
read, cache creation, output, and separately reported reasoning. Reasoning is an
output subset and is not added again to total tokens. Missing reasoning reporting
does not establish zero reasoning. Token/output ratios are diagnostic, not targets.

Combined adds provider totals; it does not deduplicate tasks across providers or
join cross-provider edit/verify chains. Auto-review usage describes permission
review, not independent requirements acceptance. Token counts are not monetary
costs. Logs and task outcomes may cover different populations, so the report does
not divide all historical token usage by unrelated successful task records.

## Acceptance standard provenance

Register the standard and real execution conditions before implementation. The
recorder accepts optional provenance flags:

```bash
agent-level record start \
  --repo /absolute/path/to/project --source codex \
  --model unknown --reasoning-effort unknown --harness-version unknown \
  --criteria 'The registered tests cover the required behavior and regression cases' \
  --criteria-version 1 --criteria-author unknown \
  --criteria-review-source unknown --criteria-reviewer unknown \
  --timeout 300 -- python3 -m unittest discover -s tests -v
```

Use actual known values. Review source may be `human`, `independent_model`,
`template`, `self` or `unknown`; a declaration does not prove review happened or
that an independent model is correct. `--criteria-review-ref` can record the
review's local reference. Repeat `--session-id` when explicitly associating several
sessions with the task; it is never guessed from transcript text.

New registrations retain a hash-linked frozen plan. Finish checks that the
registered criteria, command and scoring conditions have not changed before
running acceptance. Existing records without this addition remain readable and
their missing provenance remains unknown. This local consistency check cannot
prevent a party that controls all files from rewriting the evidence.

## Human review and interventions

Human review is a separate retrospective operation after finish:

```bash
agent-level record review --task-dir /absolute/path/to/task --review-file review.json
```

The input is a typed human-authored review. Do not have an agent invent a human
verdict or mark its own review as human. Review records are appended with hashes;
the acceptance verdict and its evidence are preserved. Missing intervention counts
stay unknown. Use the documented fields in [the task protocol](ANTHROPIC.md) to
record selection, reviewer, time, result and intervention types/counts.

Generate a reproducible review plan, then have people review the selected tasks:

```bash
agent-level record review-plan --workspace /absolute/path/to/workspace --seed 20260930
```

The plan includes all failures and unknowns plus a random 20% of successes within
evaluation groups, rounded up. Record the selection method; generating the plan
does not perform human review or claim that a fixed sample percentage proves quality.

## Diagnose a result

Groups have stable opaque `group_id` values based on evaluation conditions.
Failure/unknown diagnostics expose opaque `task_ref` and `trial_ref` values, fixed
reason labels and outcomes. Display order does not identify a group.

Reasons distinguish acceptance failure, timeout, interruption, launch failure,
output limits and missing evidence. Requirement, environment and grader problems
are human-review categories; they are not inferred from a failed exit code.

Resolve a task reference explicitly in the local workspace:

```bash
agent-level record locate --workspace /absolute/path/to/workspace --task-ref task-REFERENCE
```

Default reports omit raw task/session IDs, commands, criteria and record paths.
Opaque references are pseudonymous identifiers, not a guarantee of anonymity.
The explicit local lookup reveals the matching record directory for inspection;
the evaluator remains read-only and never executes imported evidence.
