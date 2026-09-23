# OpenAI Evaluation Guidance and Project Status

Official OpenAI documentation reviewed 2026-09-23:

- [Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices): objectives, representative datasets, metrics, continuous evaluation, and grader calibration.
- [Evaluate agent workflows](https://developers.openai.com/api/docs/guides/agent-evals): traces, graders, datasets, and repeatable eval runs for agents.
- [Deprecations](https://developers.openai.com/api/docs/deprecations): status and dates for the legacy Evals platform.

These pages provide official OpenAI guidance for designing evaluations. They do not define an official L0–L7 level scale, a universal pass threshold, a certification, or a required local JSON format. The thresholds and protocol described elsewhere in this repository are project choices.

## Evaluation design from the official guidance

OpenAI's [evaluation process](https://developers.openai.com/api/docs/guides/evaluation-best-practices) is: define the objective and success criteria, collect a dataset that reflects the intended use, choose metrics, run and compare evaluations, then continue evaluating as the system changes. Logs, production failures, typical cases, edge cases, and adversarial cases can supply tasks. A score is meaningful only for the task distribution and criteria used to produce it.

For an agent, begin with an end-to-end [trace](https://developers.openai.com/api/docs/guides/agent-evals) when diagnosing behavior. A trace can expose model calls, tool calls, guardrails, and handoffs. Once a failure mode and its desired behavior are clear, put representative cases in a versioned dataset and run them repeatedly to compare changes. A trace supports diagnosis; it does not itself establish that the task succeeded.

| Area to evaluate | Concrete question | Evidence to retain |
|---|---|---|
| Instruction following | Did the agent follow the applicable instructions and constraints? | Task instructions, trace, rubric and grade |
| Functional correctness | Did the output or final environment state meet the acceptance criteria? | Output or artifact, reference or executable check, grade |
| Tool selection and data precision | Were the needed tools called with the correct arguments? | Tool calls and returns, expected behavior, grade |
| Handoffs, when used | Did the agent transfer control at the right boundary? | Trace with routing and handoff events, grade |

These areas follow the [single-agent and multi-agent examples](https://developers.openai.com/api/docs/guides/evaluation-best-practices) and the [agent workflow guide](https://developers.openai.com/api/docs/guides/agent-evals). A task need only grade the areas relevant to it. For coding work, an executable acceptance check should verify the result; tool activity and a completed conversation are weaker signals.

OpenAI's [best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices) describe numerical or executable checks, human review, and model judges. Use a task-specific rubric and a pass/fail decision when appropriate. Calibrate automated or model grades against human labels, inspect disagreements, and account for position and verbosity bias in model comparisons. Human judgments can also disagree, so record the rubric and adjudication method. These are design recommendations, not fixed weights or thresholds from OpenAI.

## Mapping to this repository

This repository currently imports Codex session logs and can assess registered task outcomes through its existing provider-neutral task records. Its task report names that view `anthropic_evaluation`, because the implemented task/trial/outcome method is documented in [ANTHROPIC_EVALUATION.md](ANTHROPIC_EVALUATION.md). A separate project-defined [`self_improvement_evaluation`](IMPROVEMENT_EVALUATION.md) compares controlled before/after results. There is **no separate OpenAI evaluation engine, `openai_evaluation` report field, OpenAI dashboard connection, or Evals API call**. This file documents how to design an OpenAI-guided evaluation; it does not claim that such a report is already generated.

| OpenAI-guided requirement | Current local evidence or gap |
|---|---|
| Objective and task-specific success criteria | `acceptance_criteria` in registered task records; criteria quality requires review |
| Representative, versioned dataset | `suite_id` and `suite_version` exist; representativeness is not measured |
| Trace and end result | `transcript_ref`, grader evidence, and `outcome` can be imported; completeness and truth are not guaranteed by a reference or hash |
| Repeatable comparisons | Controlled tasks group by source, suite, model, and harness; clean environment and comparable runs need external assurance |
| Human calibration of automated grades | A calibration reference is required for imported model graders; agreement is not computed |
| Continuous evaluation | [AUTO_EVALUATION.md](AUTO_EVALUATION.md) describes an agent-run daily record workflow; there is no background scheduler or OpenAI service integration |

For a concrete OpenAI-guided suite, define the intended user task and acceptance decision before running the agent. Include representative successes and failures, pin the dataset and grader versions, keep the model and harness conditions, retain a trace and output artifact for every run, and report missing runs separately from failures. Review a sample of traces and grades, especially surprising passes or failures. These are local implementation recommendations derived from the official guidance, not an OpenAI protocol.

## Legacy Evals platform status

OpenAI's [deprecation notice](https://developers.openai.com/api/docs/deprecations) says the Evals platform was deprecated on 2026-06-03, existing evals become read-only on 2026-10-31, and the Evals dashboard and API are scheduled to shut down on 2026-11-30. The grader APIs documented for that workflow are also in transition. Do not treat the legacy Evals API as a durable dependency for this repository. Recheck the official notice before planning any platform integration.

## Interpretation limits

An evaluation result applies to its defined tasks, environment, model, harness, graders, and time period. Codex log counts, successful tool returns, and session completion do not prove task success. A score from the existing `anthropic_evaluation` report is not an OpenAI-issued score, and this document does not turn the project's L0–L7 heuristic into an OpenAI standard.
