# Local self-improvement comparison

This repository can now compare a workflow before and after an agent changes a prompt, tool, or workflow. The comparison answers a narrow question: **did the changed version complete more of the same local tasks without corrective human intervention, while preserving task success?** It is a project-defined method, not an OpenAI or Anthropic level standard.

## How to obtain independent evidence

1. An evaluator **outside the improving agent** freezes a holdout task set, acceptance criteria, grader versions, and the number of trials before seeing the proposed change. Keep the holdout tasks and reference solutions away from the improving agent. The plan must list every task, including tasks that later fail or remain unrun.
2. The evaluator runs the baseline and candidate with the **same model**, comparable clean environments, the same tasks and graders, and at least three trials per task per version. Record the exact harness versions, full session exports, final artifacts, grader results, and corrective human interventions. Initial task specification and planned approval are not corrective interventions.
3. The agent's failure analysis, proposed change, and rollback procedure are retained as files. The evaluator stores these with the plan and raw trial evidence, then exports the existing schema 1.1 `tasks` records. The evaluator should review whether the change was actually proposed by the agent and applied before candidate runs; file hashes alone cannot establish authorship or chronology.
4. Run the read-only assessment below. Re-run the comparison on a later frozen suite to check that gains persist. Report every attempted candidate; selecting only the best comparison invalidates the stated significance level.

Install and activate the workspace venv as shown in the [quick start](../README.md#quick-start), then run:

```bash
agent-level-assess --source codex --eval-results paired-results.json \
  --evidence-root ./paired-evidence --format txt+html
```

OpenAI Docs recommends representative datasets, task-specific criteria, traces, grader calibration, and continuous evaluation. Anthropic's agent evaluation guidance distinguishes tasks, trials, transcripts, outcomes, and repeat reliability. The frozen comparison and minimum trial count below are **local choices** derived from those principles. See [OpenAI evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices), [OpenAI agent evals](https://developers.openai.com/api/docs/guides/agent-evals), and [Anthropic agent evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).

## Input extension

Add `improvement_comparisons` to an explicit schema 1.1 eval file. Both versions' controlled task records must be present in its `tasks` array. The baseline and candidate must share source, suite ID/version, model, task IDs, acceptance criteria, reference solutions, required graders, grader versions, and planned trial counts; only `harness_version` changes. A comparison cannot use automatically discovered daily records.

```json
{
  "schema_version": "1.1",
  "tasks": ["... existing controlled task records for both versions ..."],
  "improvement_comparisons": [{
    "source": "codex",
    "suite_id": "local-workflows",
    "suite_version": "holdout-1",
    "model": "actual-model-id",
    "baseline_harness_version": "workflow-v1",
    "candidate_harness_version": "workflow-v2",
    "change_kind": "workflow",
    "plan_ref": "plan.json", "plan_sha256": "64 lowercase hex characters",
    "feedback_ref": "feedback.json", "feedback_sha256": "64 lowercase hex characters",
    "change_ref": "change.diff", "change_sha256": "64 lowercase hex characters",
    "rollback_ref": "rollback.md", "rollback_sha256": "64 lowercase hex characters"
  }]
}
```

The hashed `plan.json` must contain `kind: "improvement_plan"`, every identity and version field from the comparison above, `task_ids` listing the frozen task set, `planned_trials_per_task` of at least 3, a timezone-aware `registered_at` before all trials, `grader_versions` mapping each task ID to its grader ID/version map, and `task_specs_sha256`. The last field is SHA-256 of the baseline task-spec array, sorted by `task_id`, with each object containing `task_id`, `acceptance_criteria`, `reference_solution_ref`, `required_graders`, and `planned_trials`; encode as UTF-8 JSON with sorted keys, no spaces, and no ASCII escaping. This ties the plan to the task definitions supplied for comparison, although it cannot prove the plan was truly registered at that time.

Each controlled task must have exactly that many completed trials. Each trial needs `task_id`, `transcript_kind: "session_export"`, `human_interventions`, and all fields of the existing [task evidence protocol](ANTHROPIC.md). Its code grader `command_result` and `task_outcome` evidence files must also include the matching `task_id`. Artifact IDs and transcript hashes must be unique across all compared trials. The referenced files must be beneath `--evidence-root`, regular files without symlink traversal, with matching SHA-256 hashes.

## Scoring and limits

For each task and version, the evaluator calculates ordinary success and **autonomous success** (`passed` and zero corrective human interventions). It averages each rate equally across tasks, then reports the candidate minus baseline difference, improved/regressed/unchanged task counts, and a one-sided exact sign test on task-level autonomous-success differences.

| Status | Meaning |
|---|---|
| `insufficient_evidence` | Missing local evidence, incomplete trials, changed rubric, mismatched task set, or broken hashes. No gain is computed. |
| `no_observed_gain` | Autonomous success did not increase. |
| `gain_with_regressions` | Average autonomous success increased, but at least one task's autonomous or overall success fell. |
| `observed_gain` | Positive average without task regression; task-level sign test does not meet this project's p≤0.05 threshold. |
| `supported_gain` | Complete locally checked evidence, positive average without task regression, and one-sided task-level sign test p≤0.05. |

`supported_gain` is **not proof of independent execution or causality**. The JSON field `independent_execution_verified` remains `false`. Hashes establish consistency of supplied files, not that the holdout was secret, the evaluator was independent, the runs were isolated, the agent authored the change, or all attempted variants were reported. An outside evaluator must control those conditions and retain the raw evidence. The comparison is kept separate from the L0–L7 heuristic; it does not automatically promote a self-reported L6 declaration.
