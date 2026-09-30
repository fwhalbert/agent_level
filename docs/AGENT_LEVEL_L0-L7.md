# Agent Level: L0–L7

Ruleset **1.0** supports Claude Code, Codex and combined reports. It assesses the division of engineering work in a selected project and period. It is a project-defined rubric, not a calibrated capability benchmark or an industry certification.

## 1. Evidence and results

| State | Meaning |
|---|---|
| `DEFAULT` | L0 is achieved by default for every source, with or without logs. |
| `OBSERVED` | Logs support a workflow candidate, L1–L4. A tool call is an attempt, not proof of task success. |
| `NOT VERIFIED` | This level or an earlier required level lacks evidence. |

Reports retain `observed_level`, `current_level`, and `assessment_basis`. All eight levels have requirements in the report. Log observations support L1–L4; L5–L7 remain `NOT VERIFIED` and serve as reference definitions. Task acceptance results and improvement comparisons have separate views and do not promote engineering levels.

## 2. Level definitions

| Level | Meaning | Human role |
|---|---|---|
| L0 | Human implements and verifies; AI is at most a reference | Developer |
| L1 | AI provides explanations or suggestions that a human integrates | Developer |
| L2 | AI edits directly with human guidance on steps | Step decision maker |
| L3 | Agent implements and verifies a specified task | Task initiator |
| L4 | Agent delivery repeats across tasks and days | Supervisor |
| L5 | Agent picks up tasks, delivers changes, repairs CI and tracks outcomes | Specification and acceptance owner |
| L6 | Results drive prompt, tool or workflow improvements with evaluation and rollback | Improvement and governance owner |
| L7 | A system researches, builds, evaluates and deploys successive systems under human governance | Research and governance owner |

L3 and L4 require the preceding log level. L0 is the default baseline and remains achieved at higher levels. L1–L2 describe distinct workflows. L5–L7 describe capabilities that the current log observations cannot establish. L7 is a specialized research direction, not a required target for application teams.

## 3. Log observation

- No assistant activity or tool calls: default L0, with `assessment_basis: "default"` and `observed_level: null`, even if human prompts exist.
- Assistant or investigation activity without explicit edits: L1 candidate.
- `Edit`, `Write`, `NotebookEdit` or `apply_patch` calls: L2 candidate.
- L3 requires at least 50 tool calls, 3 human inputs, a tool/input ratio of at least 3, and one session containing an edit followed by a build/test attempt.
- L4 requires L3 and at least 3 such sessions over at least 2 UTC days.

Edit and verification must have valid timestamps and occur in order within the same session, source and selected period. Git status, PR operations and CI queries are not build/test verification. Shell writes and nested JavaScript calls are not inferred from text. Counts are sample floors, not statistically calibrated measures of quality or autonomy. L0 needs no evidence; logs alone cannot demonstrate L5–L7.

## 4. Collection and privacy

Selected session logs, project task records and explicitly imported task evidence are read:

```text
<claude-dir>/projects/**/*.jsonl
<claude-dir>/stats-cache.json
<codex-dir>/sessions/**/*.jsonl
<codex-dir>/archived_sessions/**/*.jsonl
<project>/.codex/agent_level/tasks/*/results.json
<project>/.claude/agent_level/tasks/*/results.json
<explicit task results and locally checked evidence>
```

Defaults are `CLAUDE_DIR` or `~/.claude`, and `CODEX_HOME` or `~/.codex`. Authentication files, `.env`, SSH keys, Codex history or state databases are excluded; session symlinks are not followed. Raw content is used only in memory for recognition. Reports contain aggregate counts, fixed tool categories, dates, rules, and evidence states. They omit session IDs, prompts, source, raw commands, tool arguments, and file contents. Invalid JSON, fields, timestamps, unreadable files, and opaque tools are diagnosed as counts.

**Claude:** Exclude sidechains, meta records, pure tool results, IDE notices, and system wrappers; retain real text, images, documents, and slash commands. Inspect mixed messages as a whole. Count assistant `tool_use`, deduplicate by UUID, and count top-level usage only.

**Codex:** Use local rollout `session_meta` for session and subagent identity. Count function/custom/local-shell `response_item` calls, not duplicate notifications. Prefer `user_message` as human input when available; otherwise use user response items, excluding injected context and subagent input. Deduplicate response usage by `response_id`; use positive deltas of cumulative tokens when response usage is absent, with earlier data establishing the baseline. Deduplicate session/archive records and do not double count token or reasoning summaries. Internal calls in JS orchestration cannot be reliably expanded; count and diagnose the wrapper without executing logged code. [OpenAI App Server documentation](https://learn.chatgpt.com/docs/app-server) covers persistent JSONL and archival; the public [codex exec JSON format](https://learn.chatgpt.com/docs/non-interactive-mode) is a different format and is not imported here.

## 5. Metric interpretation

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

## 6. Project isolation and combined reports

Installed assessment commands and `python3 assess.py` default to the current project. Existing target-project logs remain available; cloning this tool does not reset them. The checkout contains no personal task results, logs, reports or enabled hooks; the checked-in example reports use explicitly synthetic data. Bootstrap does not create or modify the target project's `.gitignore`; all ignore rules are managed by the target project. Task-record discovery searches the project and ancestors but filters records by task repository. Invalid automatic records are isolated and reported as diagnostics; attributable rejected trials remain unknown. Unreadable or unassigned records cannot be included in task denominators. Global stats-cache is excluded in project mode. Keep task evidence local and exclude its directories from version control.

Combined log statistics add counts, recalculate ratios and union dates. They never join edits and verification across sources.

## 7. Time and reporting

Log date filters use inclusive UTC calendar dates; `--days N` includes today. Invalid or conflicting dates are errors. Undated log records are excluded when a date filter is active. Task model/effort filters apply to the task result view, not log candidates.

Text, Markdown, JSON and offline bilingual HTML share the same results. JSON includes per-level gates, the log candidate and its basis. Missing data directories yield a valid default `L0` report. `DEFAULT` is distinct from observed behavior. Parse diagnostics and partial tool visibility remain visible so users can assess the coverage.

The separate task outcome and improvement views retain their own evidence states and statistics. [References](REFERENCES.md) explain the methods and their limits. Independent capability claims require representative tasks, trusted evidence collection, calibrated graders and external review; the local tool does not certify those conditions.
