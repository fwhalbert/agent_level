# AI Engineering Levels: L0–L7 Local Observation Rules

> Ruleset **2.0**, reviewed 2026-09-21. Supports Claude Code, Codex, and combined views.

This is a project-defined heuristic for finding workflow improvement opportunities. It is not an industry standard, human capability certification, or productivity score.

## 1. Assessment target and rule review

The assessment observes how humans and AI divide engineering execution and control: task breakdown, edits, verification, delivery, and improvement. A shift from step-by-step direction toward setting goals, acceptance criteria, and governance boundaries is relevant. Fewer human inputs alone do not imply better outcomes.

| Earlier issue | Ruleset 2 decision | Reason |
|---|---|---|
| Missing logs meant L0 | Return Unknown | Missing data is not evidence of absent capability |
| Tool/reply volume directly implied L3 | Require edit then verification in one session; remove reply ratio gate | Searches, retries, and fragmented replies inflate counts |
| L4 required delegation | Require repeated engineering behavior across sessions and days | One agent can also follow a repeatable workflow |
| Git/PR/CI calls counted as verification | Count only build/test attempts | Git status or PR queries do not establish correctness |
| True config flags were marked PASS | Mark L5–L7 `DECLARED` | Self-reports lack independent proof |
| L7 was every team's destination | Treat it as a specific research direction | Delivery, improvement, and recursive research are different abilities |
| Client formats differed | Normalize events and retain source diagnostics | Log detail should not determine level |

Sample floors remain to avoid classifying an isolated event, but the numbers have **not been statistically calibrated across teams**. Do not increase tool calls, split sessions, or reduce necessary human involvement merely to raise a level.

## 2. Level definitions

| Level | Name | Primary human role | Capability represented |
|---|---|---|---|
| L0 | Manual Engineering | Developer | Human performs engineering; AI is at most a reference |
| L1 | AI-assisted Coding | Developer | AI explains, suggests, completes, or generates locally; human integrates |
| L2 | Interactive AI Coding | Step decision maker | AI edits directly; human frequently chooses the next step |
| L3 | Agent Coding | Task initiator | Agent edits and attempts verification around a task |
| L4 | Agent-first Engineering | Supervisor | Engineering workflow repeats across sessions and days, with one or more agents |
| L5 | Autonomous Engineering | Specification and acceptance owner | Agent picks up, implements, verifies, delivers, repairs CI, and tracks tasks |
| L6 | Self-improving Engineering System | Improvement and governance owner | Outcomes drive changes to prompts, tools, or workflow, with evaluation and rollback |
| L7 | Governed Recursive Self-Improvement | Research and governance owner | System iterates a next-generation AI system with research, build, evaluation, deployment, and human governance |

L0/L1 may happen outside these logs, such as editor completion. L2 may be an intentional collaboration style. L7 does not mean unrestricted self-modification.

## 3. Evidence states

1. **Unknown:** No analyzable interaction or activity. JSON uses `current_level=null`.
2. **OBSERVED:** Log behavior meets a candidate level. This does not prove task completion, passing tests, or a change in the human role.
3. **DECLARED:** Self-reported config meets L5–L7 conditions, without independent verification. It must not be labeled verified.

Reports include `observed_level` (at most L4), `current_level` (including declarations, at most L7), and `assessment_basis`. A full capability evaluation needs outcomes, acceptance records, and sampled audit. The level rules do not read outcome ledgers. The independent [Anthropic method view](ANTHROPIC.md) summarizes explicit task results; the two methods cannot promote each other's level or fill missing evidence.
An optional [local self-improvement comparison](IMPROVEMENT_EVALUATION.md) now checks paired before/after task evidence. Its result is separate from the level rules and cannot automatically promote L6. An outside evaluator is still needed to establish that the holdout suite and execution were independent of the improving agent.

## 4. Automatic rules

### L0–L2

- No valid behavior record: Unknown.
- Interaction, tools, or investigation without an explicit edit tool call: L1 candidate. Logs cannot reliably distinguish L0 from L1.
- `Edit`, `Write`, `NotebookEdit`, or `apply_patch` call without satisfying L3: L2 candidate.
- Arbitrary Bash calls are not edits; dynamic shell writes are not inferred as edits.
- L0 requires a separate human review, never an inference from missing data.

### L3: Agent Coding behavior

All conditions must hold:

```text
tool_calls >= 50
humanish_user >= 3
tool_calls / humanish_user >= 3
engineering_sessions >= 1
```

An `engineering_session` has an explicit edit call followed by a build/test command attempt within the selected window, same source, and same session. Both need parseable timestamps; verification cannot precede the edit. This means only that verification was attempted after an edit. No task outcome or process exit code is checked, and one session may contain several tasks. `assistant/human` is displayed but does not gate a level because clients record messages and tool events differently.

### L4: Repeated engineering workflow

L3 plus:

```text
engineering_sessions >= 3
engineering_days >= 2  # UTC dates with the behavior above
```

Delegation, workflow calls, and a higher tool/human ratio are not required. Subagent and delegation counts cannot replace edit/verification evidence. Repetition excludes one-off behavior but does not prove long-term stability.

### L5: Autonomous delivery declaration

L4 plus all of:

```text
persistent_task_pickup          = true
autonomous_pr                   = true
autonomous_ci_repair             = true
task_outcome_tracking            = true
0 <= human_interventions_per_task <= 1.0
```

Use real engineering records for ongoing task pickup, PR or equivalent delivery review, CI repair after failure, and task outcomes. Flags must be JSON booleans; the intervention rate must be finite and nonnegative, not a string or boolean. A useful rate is corrective human interventions on completed tasks divided by completed tasks in the window. Record initial clarification, planned acceptance, and final approval separately. Use `null`, not zero, when no tasks completed. Review completion and failed tasks too, avoiding a successful-only sample. The tool does not read this denominator or outcome ledger, so L5 is `DECLARED`.

### L6: Self-improvement declaration

L5 plus all of:

```text
outcome_driven_improvement          = true
self_modify_prompts_tools_workflows = true
automated_eval_before_rollout       = true
rollback_supported                 = true
```

Retain before/after evaluations, controls, version history, and rollback exercises. One manual prompt change is not sustained self-improvement.

### L7: Governed system iteration declaration

L6 plus all of:

```text
autonomous_research_train_eval_deploy = true
next_generation_system_iteration     = true
human_governance_gate                  = true
```

Evidence should include research hypotheses, system build or training, independent evaluation, controlled release, iteration records, and a human governance gate. A config edit alone cannot prove L7. This is a specific research capability, not a necessary target for application teams.

### Cumulative gates

L3–L7 are cumulative. If an earlier gate fails, later gates are `NOT VERIFIED`; high-level declarations cannot compensate for sparse observed data. This conservative choice can underrate efficient teams with small samples.

## 5. Collection and privacy

Only selected session logs and optional evidence config are read:

```text
<claude-dir>/projects/**/*.jsonl
<claude-dir>/stats-cache.json
<codex-dir>/sessions/**/*.jsonl
<codex-dir>/archived_sessions/**/*.jsonl
ai-level-evidence.json
```

Defaults are `CLAUDE_DIR` or `~/.claude`, and `CODEX_HOME` or `~/.codex`. Authentication files, `.env`, SSH keys, Codex history or state databases are excluded; session symlinks are not followed. Raw content is used only in memory for recognition. Reports contain aggregate counts, fixed tool categories, dates, rules, and evidence states. They omit session IDs, prompts, source, raw commands, tool arguments, and file contents. Invalid JSON, fields, timestamps, unreadable files, and opaque tools are diagnosed as counts.

**Claude:** Exclude sidechains, meta records, pure tool results, IDE notices, and system wrappers; retain real text, images, documents, and slash commands. Inspect mixed messages as a whole. Count assistant `tool_use`, deduplicate by UUID, and count top-level usage only.

**Codex:** Use local rollout `session_meta` for session and subagent identity. Count function/custom/local-shell `response_item` calls, not duplicate notifications. Prefer `user_message` as human input when available; otherwise use user response items, excluding injected context and subagent input. Deduplicate response usage by `response_id`; use positive deltas of cumulative tokens when response usage is absent, with earlier data establishing the baseline. Deduplicate session/archive records and do not double count token or reasoning summaries. Internal calls in JS orchestration cannot be reliably expanded; count and diagnose the wrapper without executing logged code. [OpenAI App Server documentation](https://learn.chatgpt.com/docs/app-server) covers persistent JSONL and archival; the public [codex exec JSON format](https://learn.chatgpt.com/docs/non-interactive-mode) is a different format and is not imported here.

## 6. Metric interpretation

| Metric | Meaning and limit |
|---|---|
| tool/human | Tool calls divided by human inputs; zero denominator displays zero, not infinite autonomy |
| assistant/human | Within-source context only, not a level gate |
| verification share | Build/test shell calls divided by all shell calls; attempts only |
| engineering_sessions | Sessions with edit followed by verification, not completed tasks |
| engineering_days | UTC dates with that behavior |
| input_tokens | Includes cached input; Claude cache reads/writes are added, Codex input already includes cache |
| cache_hit_ratio | `cache_read / input_tokens`; not a direct cost-saving rate |
| cache_reuse | `cache_read / cache_creation`, shown only with a Claude-only denominator |
| delegation | Collaboration signal, not a hard gate |

Shell categories are search/read/build/test/git/python/node/docker/ssh/pr/ci/other. Quoted separators and heredoc bodies are not separate commands. Each call gets one primary category, so complex commands may undercount some behavior.

## 7. Separate and combined statistics

Claude and Codex are scanned separately. Combining adds counts and recalculates ratios, unions active and engineering dates, namespaces sessions by source, and reruns the rules. It never averages levels, joins an edit and test across sources, or infers a unique cross-source task count. Claude stats-cache remains separately identified. Evidence scopes are `sources.claude`, `sources.codex`, and `combined`. Legacy top-level evidence applies only to the combined view in multi-source mode; explicit single-source runs retain compatibility. A PR in one source and CI repair in another do not automatically satisfy either source's declaration.

## 8. Time and sample boundaries

All dates use UTC; timestamps without timezone are interpreted as UTC. `--since` and `--until` include their calendar dates, implemented internally as `[since, until+1day)`. `--days N` covers N UTC calendar days including today. Reversed dates or conflicting filters are errors. Records without valid timestamps are excluded when a window is set. Edits before the window cannot form an in-window engineering chain; earlier cumulative token use only establishes a baseline. Personal statistics from September 2026 in the earlier specification are historical v1 examples, not v2 calibration data. Rerun assessment when rules, windows, or parser coverage change.

## 9. Report and future evidence

Text, Markdown, JSON, and HTML show source, level basis, requirements and gaps, behavior counts, data quality, and limitations in English. HTML opens offline with source and method switching. JSON v2 wraps separate and combined results in `reports`, includes program and ruleset versions, and uses null for Unknown. L5–L7 display both declaration status and the highest observed behavior level.

Improving validity requires auditable task outcomes such as `task_id`, `acceptance_criteria`, `completed`, `human_interventions`, `build_pass`, `test_pass`, `pr_created`, `ci_pass`, `tokens`, and `wall_time`. Completion, failure recovery, task cost, intervention, and improvement effects should be computed only with suitable evidence; this level ruleset does not invent those scores.

## 10. Sources and the second assessment

The levels and numeric thresholds are project heuristics, not a validated unified standard. [REFERENCES.md](REFERENCES.md) explains what Anthropic, SWE-bench, METR, SPACE, DORA, and DeepMind support and what they do not. A default run also includes the independent [Anthropic method assessment](ANTHROPIC.md). It does not reuse L0–L7 call counts, declarations, or cumulative gates. Missing task outcomes produce insufficient evidence; explicit `--eval-results` can supply task records. The view is not Anthropic certification, and local evidence checking is not independent audit.
