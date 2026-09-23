# Assessment Sources and References

Reviewed 2026-09-23. The links below are primary sources from authors, research institutions, or product providers.

The L0–L7 names, cumulative gates, and numeric thresholds such as 50 tool calls, 3 human inputs, 3 engineering sessions, 2 UTC days, and at most 1 human intervention per task are **project heuristics without statistical calibration or independent validity testing**. The references do not validate those thresholds.

## Method directly used

**Anthropic (2026). [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).**

Distinguishes task, trial, grader, transcript, and outcome; emphasizes explicit success criteria, repeated trials, final-result checks, grader design, and human review. The Anthropic view organizes evidence and outcomes along these lines. The article defines neither this project's L0–L7 scale nor its JSON fields, default k, or completeness gates. See [ANTHROPIC_EVALUATION.md](ANTHROPIC_EVALUATION.md) for the implementation mapping.

**Anthropic, [Define success criteria and build evaluations](https://platform.claude.com/docs/en/test-and-evaluate/develop-tests).**

The Claude Platform documentation covers explicit success criteria and code, human, and model grading. It does not prescribe this repository's protocol or thresholds.

**OpenAI, [Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices) and [Evaluate agent workflows](https://developers.openai.com/api/docs/guides/agent-evals).**

These official OpenAI documentation pages describe task-specific objectives, datasets, graders, traces, and repeated evaluation. They do not define a universal level scale or validate this project's scoring rules. [OPENAI_EVALUATION.md](OPENAI_EVALUATION.md) maps that guidance to the project's current capabilities and gaps. The [OpenAI deprecations page](https://developers.openai.com/api/docs/deprecations) supplies the current legacy Evals platform timeline.

## Related research and engineering methods

| Source | Supports | Does not support |
|---|---|---|
| Jimenez et al. (2023), [SWE-bench](https://arxiv.org/abs/2310.06770) | Measuring resolution of real repository issues | More tool calls mean more capability; any session is a completed task |
| METR (2025), [Measuring AI Ability to Complete Long Software Tasks](https://metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks/) | Relating difficulty, human completion time, AI completion probability, and uncertainty | Agent runtime equals human-equivalent task horizon |
| Forsgren et al. (2021), [The SPACE of Developer Productivity](https://www.microsoft.com/en-us/research/publication/the-space-of-developer-productivity-theres-more-to-it-than-you-think/) | Productivity is multidimensional and cannot be inferred from activity alone | One call or message count represents productivity |
| DORA, [Software delivery performance metrics](https://dora.dev/guides/dora-metrics/) | Observing delivery throughput and instability | Automatically assigning an autonomy level to a person or agent |
| Morris et al. (2024), [Levels of AGI](https://deepmind.google/research/publications/66938/) | Separating performance, generality, and autonomy while considering deployment | Being the original standard for this project's L0–L7 scale |

These sources address different targets: agent task capability, developer productivity, software delivery, and general intelligence are not interchangeable. Citations explain methods and limits; they do not imply industry certification, a valid ranking, or endorsement by the authors.

Validating these levels would require human-labeled task samples, checks of log recognition accuracy, testing level predictions against actual task outcomes, and replication across independent teams and tasks. This project has not completed those steps.

## Sampling uncertainty

[NIST/SEMATECH — Confidence intervals](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm) describes the Wilson interval for a proportion. Since version 2.2, complete daily task groups use a 95% Wilson interval. It relies on a binomial sampling approximation and does not remove selection bias or certify reliability. Controlled groups containing multiple tasks do not directly apply Wilson intervals to pooled trials.
