# Anthropic Method Assessment and Result Import

Program 1.0.0 / method implementation 1.1. One run produces an **L0–L7 heuristic view**, an **Anthropic-style task evaluation**, and an optional **local self-improvement comparison**. HTML can show each view or all views, by source. The improvement comparison is documented in [IMPROVEMENT_EVALUATION.md](IMPROVEMENT_EVALUATION.md).

Official sources:

- [Anthropic, “Demystifying evals for AI agents”](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents), 2026-01-09: the primary source for agent task, trial, grader, transcript, outcome, repeated-run, and harness concepts.
- [Claude Platform Docs, “Define success criteria and build evaluations”](https://platform.claude.com/docs/en/test-and-evaluate/develop-tests): guidance on explicit criteria and code, human, and model grading.

These are official Anthropic guidance, not an Anthropic certification standard or a prescribed schema. See [REFERENCES.md](REFERENCES.md) for related research and its limits.

## Method and implementation boundary

Anthropic describes an evaluation method, not a unified level scale, certification standard, or fixed JSON protocol. The task/trial/grader/transcript/outcome distinction follows its method. This project's fields, completeness rules, default k, and statistical estimators are local design choices. The `source` field can be `claude` or `codex`: the method is applied to either agent's evidence and does not imply Anthropic has evaluated or endorsed the result.

| Official guidance | Mapping in this project | Boundary |
|---|---|---|
| Define a task with clear success criteria and a working reference solution ([agent evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)) | `acceptance_criteria`; `reference_solution_ref` required for controlled tasks | The importer checks presence, not quality or solvability |
| Use clean, comparable trials and record transcripts and final outcomes ([agent evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)) | `environment_reset`, `transcript_ref`, `outcome`, model and harness identity | A reset declaration and file hash cannot prove independence or outcome truth |
| Choose code, model, or human graders; calibrate model grading with people ([Claude Platform Docs](https://platform.claude.com/docs/en/test-and-evaluate/develop-tests)) | Required grader records, with a calibration reference for model graders | The importer does not run graders or measure human agreement |
| Review traces and report repeated-run reliability ([agent evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)) | Trace references and complete controlled-group pass@1, pass@k, pass^k estimates | No trace review is automatic; estimators depend on task design and trial independence |

| Step | Local implementation | Still needs human or external assurance |
|---|---|---|
| Task and criteria | Record acceptance criteria and planned graders; controlled mode also needs a reference solution | Clear, solvable, representative tasks and requirement coverage |
| Trial and environment | Read trial identity, time, and reset declaration | Isolation of services, dependencies, accounts, caches, and cross-session memory |
| Transcript | Check reference and optionally local file hash | Complete trace export and sampled review |
| Grader | Read results and versions; optionally check exit code and JUnit | Grader correctness, resistance to gaming, partial credit rules |
| Outcome | Link graders and outcome; optionally check local hashes and content | Artifact correctness and independent audit |
| Repeat reliability | Compute pass@1, pass@k, pass^k for complete controlled groups | Trial independence, task difficulty, sample selection |
| Uncertainty | Missing-result bounds and 95% Wilson interval for complete daily groups | Between-task variation, representativeness, stability |

The evaluator is read-only and never executes commands from imported files. Evidence references are not opened by default. `--evidence-root` enables reads within that directory. `--project-dir` automatically checks discovered existing daily records.

## Existing sessions and daily activity

Install and activate the workspace venv as shown in the [quick start](../README.md#quick-start). The examples below use `agent-level-assess` from that environment.

To review existing Claude/Codex work without defining new tasks:

```bash
agent-level-assess --project-dir /path/to/workspace -o reports/workspace-history/report
agent-level-assess --project-dir /path/to/workspace/repos/example-project --days 30
```

Project matching uses log `cwd` in the selected directory and descendants. It excludes similarly named siblings and diagnoses records with no working directory; it does not guess from transcript text. Codex updates the directory at `turn_context`; Claude uses the recorded directory and carries it forward within a file. Project mode skips the global Claude stats cache. It finds `.codex/agent-eval/tasks/*/results.json` and `.claude/agent-eval/tasks/*/results.json` in the project or ancestors, filters by task `repo`, and checks local evidence. `--no-auto-evals` keeps only log analysis. `--eval-results` cannot be combined with project mode, preventing accidental import of another project's task data.

HTML includes “Historical activity · Completion signals”; JSON uses `anthropic_evaluation.historical_activity`:

- Counts primary sessions whose latest turn ended, was interrupted/errored, or lacks an end marker. Subagents are excluded from session counts.
- Links recognizable build/test calls to success, failure, or unknown returns by call ID. Recognized subagent verification calls are included.
- Claude uses explicit `end_turn` and synchronous `is_error`; background, timeout, and missing returns remain unknown. Codex uses task_complete/turn_aborted and explicit exit codes in linked command output.
- Opaque code orchestration is reported separately. Its internal verification is not counted, so zero recognizable verification calls does not imply no verification.

These are historical signals, not retroactive acceptance tasks. A session end does not prove requirements were met, and a successful tool return does not prove sufficient test coverage. `task_success_rate` stays null; strict task success requires registered tasks and acceptance evidence. Reports contain only aggregates, not paths, session IDs, prompts, commands, or tool output. A session's working directory does not prove all modified files belonged to that repository.

## Read-only usage

```bash
agent-level-assess
agent-level-assess --eval-results ./evidence/results.json --evidence-root ./evidence
agent-level-assess --eval-results ./evidence/results.json --eval-k 5 --days 30
```

Import without `--evidence-root` is marked unchecked. With it, each trial's files, hashes, grader content, and artifact links are checked; mismatches become unknown. This is not an independent audit. Task outcomes do not change the log-derived engineering level. Import also works without local session directories; L0–L7 then defaults to L0.

## Data protocol 1.1 (compatible with 1.0)

```json
{"schema_version": "1.1", "tasks": []}
```

Protocol 1.0 and tasks without a mode are interpreted as `controlled`, retaining reference-solution and environment-reset requirements. In 1.1, set `evaluation_mode` to `daily` or `controlled`. Synthetic demos should set top-level `"synthetic": true` to label the report; the tool does not detect fabricated data automatically.

| Task field | Type and purpose |
|---|---|
| `evaluation_mode` | `daily`: one acceptance run; `controlled`: repeat evaluation |
| `source` | `claude` or `codex` |
| `suite_id`, `suite_version` | Nonempty strings; update version when tasks or graders change |
| `model`, `harness_version` | Nonempty actual runtime conditions; distinct conditions cannot form repeats |
| `reasoning_effort` | Actual effort, such as `xhigh` or `high`; daily recorder writes `unknown` if omitted. Legacy records without this field use a documented official model default when known, otherwise `unknown`. An explicit `unknown` is retained. |
| `task_id` | Nonempty ID unique within source, mode, and evaluation conditions |
| `acceptance_criteria` | Success criteria defined before execution |
| `reference_solution_ref` | Required in controlled mode; optional in daily mode |
| `required_graders` | Nonempty, duplicate-free array of required grader IDs |
| `planned_trials` | Positive integer fixed before execution; exactly 1 for daily mode |
| `review_ref` | Optional human review of task and graders |
| `trials` | Trial array; keep tasks and planned counts even when none ran |

| Trial field | Type and purpose |
|---|---|
| `trial_id` | Nonempty ID unique within the task |
| `timestamp` | Timezone-aware ISO 8601; filtering uses UTC |
| `status` | Collector uses running / grading / completed / error / interrupted; incomplete is not success |
| `environment_reset` | JSON `true` in controlled mode; optional for daily |
| `transcript_ref` | Required trace reference; relative file path for local checking |
| `transcript_sha256` | Trace file hash for local checking |
| `artifact_id` | Trial artifact link for local checking; not an immutable snapshot |
| `graders` | Exactly the required graders, with no missing or duplicate IDs |
| `outcome` | `{"passed": true/false, "evidence_ref": "...", "evidence_sha256": "..."}` |
| `duration_seconds`, `human_interventions` | Optional finite nonnegative numbers; missing is not zero |
| `review_ref` | Optional human review of the execution trace |

Each grader has `grader_id`, `type` (code/model/human), boolean `passed`, and nonempty `evidence_ref`. Model graders also need `human_calibration_ref`. Locally checked code evidence needs `version` and `evidence_sha256`. Every required grader must agree with the outcome for a valid graded result; partial credit is not supported.

Local checking accepts these evidence files. All references are relative to the evidence root and carry SHA-256 digests:

- `command_result`: `kind`, `grader_id`, `grader_version`, `artifact_id`, integer `exit_code`, boolean `timed_out`, and `passed`. Optional `junit: {"ref": "…", "sha256": "…"}`.
- `task_outcome`: `kind`, `artifact_id`, boolean `passed`, and `graders: [{"grader_id": "…", "sha256": "…"}]`, matching the trial's grader order and hashes.
- Execution trace: `transcript_ref` and `transcript_sha256`.

An absent result may use `passed: null` and counts as unknown; do not mark it successful or failed. Tasks run through an agent or external workflow. The separate `agent-level-record` command can register daily tasks and execute predefined acceptance commands, as described in [AGENTS.md](../AGENTS.md). The evaluator itself runs no imported commands.

## Isolation, missing data, and date windows

- Group by `(evaluation_mode, source, suite_id, suite_version, model, harness_version, reasoning_effort)`; distinguish tasks by `task_id` within a group. No mixed-system average is published. `--model` and `--effort` filter imported task records and comparisons; they do not filter the historical-log L0–L7 assessment.
- Identical duplicate tasks/trials are deduplicated. A conflicting trial becomes unknown; a conflicting task cannot be scored. Other valid results remain.
- Records with unidentifiable identity are diagnosed separately and do not enter known group denominators. A complete group does not imply the entire input has no missing records.
- An incomplete group retains four outcome counts, grading coverage, graded pass rate, and planned success bounds, but does not publish complete-group acceptance or repeat probabilities.
- The planned denominator includes at least planned trials and distinct recorded trials. Missing planned trials are unrun/not supplied.
- For included tasks, out-of-window trials are excluded from success/failure, counted as unknown in the planned denominator, and reported separately. A task entirely outside the window with no missing plan is excluded.
- The file author supplies the plan and task set. The tool cannot discover tasks never exported or prove the plan was registered beforehand.
- Human review coverage is separate. A reference, structural completeness, local checking, and independent audit are different evidence levels.

## Statistical formulas

For each task, let success be `s`, failure `f`, unknown `u`, unrun `m`, and `N=s+f+u+m`:

```text
grading coverage = Σ(s+f) / ΣN
graded pass rate = Σs / Σ(s+f)             # observed subset; may be biased
planned success lower bound = mean(s/N)
planned success upper bound = mean((s+u+m)/N)
```

Bounds weight tasks equally. They describe the possible effect of missing data, not statistical confidence intervals.

For a complete controlled task with `n` trials and `c` successes:

```text
pass@1 = c / n
pass@k = 1 - C(n-c, k) / C(n, k)
pass^k = C(c, k) / C(n, k)
```

`C(a,k)=0` when `a<k`. Average equally across tasks only when every task in the group is complete and, for the latter two estimates, every task has `n>=k`. Default k=3 is a local statistic parameter, not an official threshold. With three successes in four trials and k=3, the estimates are 75%, 100%, and 25%. These differ from a theoretical `0.75³` calculation based on an assumed true single-run probability.

Daily mode has one acceptance run per task. Complete groups include acceptance rate and a 95% Wilson interval following [NIST/SEMATECH](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm). The interval assumes approximately independent, identically distributed outcomes; it does not remove task difficulty or selection bias.

## Privacy

Task identity, text, and references are used only in memory. Aggregate reports omit task IDs, raw traces, commands, grader content, and imported model/harness names. Groups receive anonymous numbers. JSON aggregate usage fields retain model names from logs.
