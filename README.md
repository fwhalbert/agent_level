# AI Engineering Assessment

Read local Claude Code and Codex logs and task evaluation evidence to produce workflow, task-outcome, and before/after improvement views. Requires Python 3.8+ and no runtime dependencies. A short Chinese introduction is available in [README.zh-CN.md](README.zh-CN.md).

| Method | Question answered | Output |
|---|---|---|
| L0–L7 heuristic model | What engineering workflow is visible? | Candidate level, requirements, and next gaps |
| Anthropic evaluation method | What evidence supports task outcomes and reliability? | Evidence status, acceptance rates, pass@1 / pass@k / pass^k |
| Local improvement comparison | Did an agent's versioned workflow change improve autonomous task acceptance on a fixed suite? | Paired before/after rates, regressions, and evidence status |

Anthropic does not define official L0–L7 levels. This tool keeps task outcome evaluation separate from its own level model. With logs but no task acceptance records, the second assessment reports insufficient evidence; tool calls are never converted into a success rate.
The improvement comparison is also project-defined. It checks supplied evidence but cannot certify independent execution; an outside evaluator must control the holdout suite and runs.

## Quick start

```bash
python3 assess.py
python3 assess.py --project-dir ~/codes/my-project
python3 assess.py --source codex --days 30
python3 assess.py --since 2026-09-01 --until 2026-09-20
python3 assess.py --eval-results results.json
python3 assess.py --eval-results results.json --evidence-root ./evidence
python3 assess.py --eval-results paired-results.json --evidence-root ./paired-evidence
python3 assess.py --format json -o -
python3 assess.py --report-name "Team Review"
```

The default title is “AI Engineering Assessment”. Reports go to `reports/YYYY-MM-DD/ai-engineering-assessment.{txt,html}`, using the local date at runtime. Rerunning on the same date overwrites files with the same name. `--report-name NAME` (also `--name`) changes the title and default filenames. Use `-o PATH` for another location; dual-format output replaces the supplied extension. The command prints absolute output paths and a browser-ready `file://` URL for HTML.

The HTML report works offline. It offers source and method selectors, expandable level checks, and JSON download. Its interface defaults to English; users can switch to Chinese, and the choice is remembered in browser local storage.

## Level assessment

| Level | Decision basis |
|---|---|
| Unknown | Insufficient logs; absence of data does not imply L0 |
| L0 Manual Engineering | Requires human confirmation |
| L1 AI-assisted Coding | Interaction or investigation without an explicit edit signal |
| L2 Interactive AI Coding | Explicit edit tool call, but L3 requirements unmet |
| L3 Agent Coding | At least 50 tool calls, 3 human inputs, a tool/human ratio of 3, and one edit-then-verification session |
| L4 Agent-first Engineering | L3 plus at least 3 edit-then-verification sessions on 2 UTC days |
| L5 Autonomous Engineering | L4 plus self-reported task pickup, PR, CI repair, outcome tracking, and at most 1 human intervention per task |
| L6 Self-improving Engineering System | L5 plus self-reported outcome-driven improvement, automated evaluation, and rollback |
| L7 Governed Recursive Self-Improvement | L6 plus self-reported system iteration, research/build/evaluate/deploy, and human governance |

Levels accumulate; none can be skipped. L3/L4 are observations of log behavior. Running a build or test does not prove that it passed or that a task was completed. L5–L7 are marked `DECLARED` because their evidence is self-reported. Thresholds are project heuristics that have not been calibrated across teams. L7 is an optional research direction.

```bash
python3 assess.py --init-config
python3 assess.py --config ai-level-evidence.json
```

The generated L5–L7 config is optional and is not overwritten by default. In multi-source mode, legacy top-level evidence applies only to the combined view. Use `sources.claude` and `sources.codex` for separate declarations and `combined` for the merged view; each scope accepts nested `l5/l6/l7` fields. Booleans must be JSON `true` or `false`. The intervention rate must be a finite nonnegative number or `null` for unknown.

## Evidence and data scope

- Claude input: `projects/**/*.jsonl` and supplemental daily `stats-cache.json`. Codex input: `sessions/**/*.jsonl` and `archived_sessions/**/*.jsonl`.
- System injections and subagent human inputs are excluded. Records and calls are deduplicated by their identifiers. Opaque code orchestration is diagnosed, so edit and verification activity may be undercounted.
- Edit-then-verification must occur within one session. Combined reports add counts before recalculating ratios; they do not join an edit in one source to a test in another.
- Project mode filters logs by `cwd` within the project and descendants. It omits the global stats cache and automatic self-report config. Session completion and successful tool return are activity signals, not task acceptance.
- Project mode discovers existing `.codex/agent-eval/tasks/*/results.json` and `.claude/agent-eval/tasks/*/results.json` in the project and its ancestors. Records are filtered by task `repo` and locally checked. `--no-auto-evals` disables discovery. It cannot be combined with `--eval-results`.
- Task result protocol 1.0/1.1 retains success, failure, unknown, and unrun outcomes. Statistics are grouped by source, model, harness, and suite version. Repeat probabilities are reported only for complete controlled groups.
- Explicit `improvement_comparisons` in a schema 1.1 result file pair two controlled harness versions on the same frozen tasks. The report computes autonomous success deltas only from complete locally checked evidence; L6 stays self-reported. See [comparison protocol](IMPROVEMENT_EVALUATION.md).
- Reports contain aggregates only, omitting prompts, source code, commands, tool arguments, and raw evidence. Local hash and content checks are not an independent audit.

The evaluator only reads, assesses, and reports. `agent_level_record.py start/finish` separately registers daily tasks, runs predefined acceptance commands, and saves evidence. [AUTO_EVALUATION.md](AUTO_EVALUATION.md) describes the workflow for agents in projects that reference it; there is no background listener. Controlled before/after trials must be run by an external harness or evaluator. This project does not provide a task executor, suite, or usage charts. JSON keeps existing aggregate usage fields for consumers.

## Command line options

| Option | Effect |
|---|---|
| `--source claude\|codex\|all` | Source; default `all` |
| `--view separate\|combined\|both` | Source views; default `both` |
| `--claude-dir PATH` / `--codex-dir PATH` | Defaults to `CLAUDE_DIR` or `~/.claude`, and `CODEX_HOME` or `~/.codex` |
| `--project-dir PATH` | Filter project logs and existing task records |
| `--no-auto-evals` | Read only historical logs in project mode |
| `--days N` | Last N UTC calendar days including today; N ≥ 1 |
| `--since DATE` / `--until DATE` | Inclusive UTC dates; cannot be combined with `--days` |
| `--eval-results PATH` | Import explicit task results and optional improvement comparisons, even without logs |
| `--evidence-root PATH` | Local evidence directory; requires `--eval-results` |
| `--eval-k N` | Repeat-trial parameter; default 3 |
| `--config PATH` / `--no-auto-config` | Supply self-reported config / disable automatic current-directory config |
| `--init-config [PATH]` / `--force` | Write config template / allow overwrite |
| `--format txt+html\|txt\|text\|md\|json\|html` | Default `txt+html`; `text` is an alias for `txt` |
| `--report-name NAME` / `--name NAME` | Report title and default filename |
| `-o, --output PATH` | Output path; `-` writes a single format to stdout |

Exit codes: `0` success; `1` config template already exists without overwrite; `2` argument, input, or output error.

## Source and verification

- `assess.py`: L0–L7 rules, config, CLI, and shared report data.
- `agent_level_record.py` and [AUTO_EVALUATION.md](AUTO_EVALUATION.md): daily task registration and acceptance evidence.
- `assessment/logs.py` and `assessment/history.py`: log adapters, merging, and historical activity.
- `assessment/anthropic.py`: task evidence and outcome statistics.
- `assessment/evidence.py` and `assessment/collection.py`: local evidence checking and record discovery.
- `assessment/web.py`: offline HTML; `assessment/references.py`: method sources.
- `assessment/improvement.py`: paired controlled comparison of autonomous task outcomes.
- `tests/`: synthetic data and regression tests.

```bash
python3 -m unittest discover -s tests -t . -v
```

See [L0–L7 rules](AI_ENGINEERING_LEVELS_L0-L7.md), [Anthropic import protocol and statistics](ANTHROPIC_EVALUATION.md), [local improvement comparison](IMPROVEMENT_EVALUATION.md), [OpenAI evaluation guidance and current project scope](OPENAI_EVALUATION.md), and [references](REFERENCES.md).
