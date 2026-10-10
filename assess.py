#!/usr/bin/env python3
"""
assess.py — Agent Level local analyzer

Specification: docs/AGENT_LEVEL_L0-L7.md

Reads:
    <claude-dir>/projects/**/*.jsonl
    <claude-dir>/stats-cache.json
    <codex-dir>/sessions/**/*.jsonl
    <codex-dir>/archived_sessions/**/*.jsonl
    project task records and explicitly imported task evidence

Does not read: .credentials.json / .env / SSH key / API key
Omits: raw prompts / source code / raw shell commands / tool arguments / file contents
        Only aggregate statistics and assessment results are reported.

Usage (after installing and activating the venv):
    agent-level-assess
    agent-level-assess --source claude
    agent-level-assess --source codex
    agent-level-assess --format txt+html
    agent-level-assess --format md
    agent-level-assess --format json -o -
    agent-level-assess --since 2026-09-01 --until 2026-09-20
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assessment.logs import (
    Metrics, scan, scan_codex, merge_metrics, parse_date, BASH_CATEGORY_ORDER,
    HUMAN_FILTER_RULES, usage_breakdown, verification_coverage, observability,
)

from assessment.anthropic import assess as assess_anthropic, filter_evals, load_evals, render_summary
from assessment.improvement import assess as assess_improvement, render_summary as render_improvement
from assessment.references import REFERENCES, METHOD_NOTE
from assessment.evidence import EvidenceReader
from assessment.guidance import EXPERIMENT_NOTE, recommended_experiment
from assessment.collection import DISCOVERY_NOTE

VERSION = "1.0.0"
RULESET_VERSION = "1.0"
# Preserve legacy entrypoint titles and filenames; the unified CLI supplies its brand.
DEFAULT_REPORT_NAME = "AI Engineering Assessment"


def report_stem(name: str) -> str:
    """Turn a display name into a safe, readable filename stem."""
    return re.sub(r"[^\w-]+", "-", name, flags=re.UNICODE).strip("-_ ").lower()


def show_progress(message: str) -> None:
    print(f"[progress] {message}", file=sys.stderr, flush=True)


def scan_progress(source: str):
    last_update = time.monotonic()

    def update(file_number):
        nonlocal last_update
        now = time.monotonic()
        if now - last_update >= 2:
            show_progress(f"{source}: processing log file {file_number}…")
            last_update = now

    return update

LEVEL_NAMES = {
    0: "Manual Engineering",
    1: "AI-assisted Coding",
    2: "Interactive AI Coding",
    3: "Agent Coding",
    4: "Agent-first Engineering",
    5: "Autonomous Engineering",
    6: "Self-improving Engineering System",
    7: "Governed Recursive Self-Improvement",
}

LEVEL_SHORT = {
    3: "L3 Agent Coding",
    4: "L4 Agent-first",
    5: "L5 Autonomous Eng.",
    6: "L6 Self-improving",
    7: "L7 Recursive SI",
}

# Heuristic sample floors, not calibrated productivity scores.
L3_MIN_TOOL_CALLS = 50
L3_MIN_HUMAN_INPUTS = 3
L3_MIN_TOOL_PER_HUMAN = 3.0
L4_MIN_ENGINEERING_SESSIONS = 3
L4_MIN_ENGINEERING_DAYS = 2


CAPABILITY_REQUIREMENTS = {
    5: ('Persistent task pickup', 'Autonomous PR', 'CI self-repair',
        'Task outcome tracking', 'Human interventions/task <= 1'),
    6: ('Outcome-driven improvement', 'Self-modify prompts/tools/workflows',
        'Automated eval before rollout', 'Rollback supported'),
    7: ('Autonomous research/train/eval/deploy', 'Next-generation system iteration',
        'Human governance gate'),
}


class Check:
    __slots__ = ("label", "ok", "detail")

    def __init__(self, label, ok, detail=""):
        self.label = label
        self.ok = bool(ok)
        self.detail = detail

    def as_dict(self):
        return {"check": self.label, "pass": self.ok, "detail": self.detail}


def num(v, fmt="{:.2f}"):
    return "n/a" if v is None else fmt.format(v)


def evaluate(m: Metrics) -> dict:
    """Derive L0–L4 from log observations; higher capabilities stay unverified."""
    gates = {
        3: [
            Check("tool_calls >= 50 (sample floor)", m.tool_calls >= L3_MIN_TOOL_CALLS, str(m.tool_calls)),
            Check("human inputs >= 3 (sample floor)", m.humanish_user >= L3_MIN_HUMAN_INPUTS, str(m.humanish_user)),
            Check("tool_calls / human >= 3", m.tool_per_human >= L3_MIN_TOOL_PER_HUMAN, num(m.tool_per_human)),
            Check("edit followed by build/test in >= 1 session",
                  len(m.engineering_sessions) >= 1, str(len(m.engineering_sessions))),
        ],
        4: [
            Check("edit followed by build/test in >= 3 sessions",
                  len(m.engineering_sessions) >= L4_MIN_ENGINEERING_SESSIONS, str(len(m.engineering_sessions))),
            Check("edit/verify activity across >= 2 UTC days", len(m.engineering_days) >= L4_MIN_ENGINEERING_DAYS, str(len(m.engineering_days))),
        ],
    }
    observed = 2 if m.edit_calls else (1 if m.assistant or m.tool_calls else None)
    for level in (3, 4):
        if all(c.ok for c in gates[level]) and observed == level - 1:
            observed = level
    gates[0] = [Check("L0 baseline", True, "Achieved by default")]
    gates[1] = [Check("AI assistance or investigation", observed is not None)]
    gates[2] = [Check("AI code edits", bool(m.edit_calls))]
    for level, labels in CAPABILITY_REQUIREMENTS.items():
        gates[level] = [Check(label, False, "Not assessed from session logs") for label in labels]
    current = observed if observed is not None else 0
    status = {level: 'DEFAULT' if level == 0 else 'OBSERVED' if level <= current else 'NOT VERIFIED'
              for level in range(8)}
    next_level = current + 1
    gaps = [c for c in gates[next_level] if not c.ok]
    note = None
    if current == 0:
        note = "L0 is achieved by default. Logs are required to observe higher levels."
    elif current == 1:
        note = "Assistance or investigation was observed; the logs do not establish completed engineering tasks."
    elif current == 2:
        note = "Code edits were observed, but the sample does not support L3; this is not a judgment of human ability."
    return {"gates": gates, "status": status, "current": current,
            "observed_level": observed, "next": next_level, "gaps": gaps,
            "below_note": note, "basis": "default" if current == 0 else "observed",
            "limitations": [
                "L0–L7 are project heuristics, not an industry certification or productivity ranking.",
                "L3/L4 are candidate levels based on log behavior; running a build/test after an edit does not prove it passed or that the task was completed.",
                "L5–L7 are reference definitions only. Session logs and task acceptance results do not establish these capabilities.",
                "Message and tool formats vary by client; assistant/human and delegation counts are not hard thresholds.",
            ]}


def level_label(level):
    return "Unknown" if level is None else f"L{level}"


KEY_METRICS = (
    ("Level", lambda r: level_label(r["current_level"])),
    ("Recognized tool calls", lambda r: f"{r['tool_observability']['recognized_tool_calls']:,}"),
    ("Opaque orchestration calls", lambda r: f"{r['tool_observability']['opaque_orchestrator_calls']:,}"),
    ("Sessions with edits", lambda r: f"{r['verification_coverage']['edited_sessions']:,}"),
    ("Edit → verify sessions", lambda r: f"{r['observed']['engineering_sessions']:,}"),
)


def render_key_metrics(reports):
    names = [name for name in reports if name != "combined"] or list(reports)
    return "\n".join(f"{label}: " + "; ".join(f"{name.capitalize()} {value(reports[name])}"
                                             for name in names)
                     for label, value in KEY_METRICS)


def window_str(m: Metrics, since, until):
    if m.first_ts and m.last_ts:
        return f"{m.first_ts.date()} .. {m.last_ts.date()}"
    if since or until:
        return f"{since.date() if since else '-'} .. {(until - timedelta(days=1)).date() if until else '-'}"
    return "n/a"


def render_report(report, markdown=False):
    """Render the shared assessment data as text or Markdown."""
    def heading(title):
        return ('## ' if markdown else '') + title

    level = report['current_level']
    anthropic = report['anthropic_evaluation']
    lines = [heading(report.get('report_name', DEFAULT_REPORT_NAME)), '',
             f"Current Level : {level_label(level)}  {report['current_level_name']}",
             f"Anthropic    : {anthropic['status_label']} (no L0–L7 level)",
             f"Next Target  : {level_label(report['next_target'])}",
             f"Source       : {report['source']}",
             f"Window       : {report['window']} (UTC)",
             f"Basis        : {report['assessment_basis']}"]
    if report['project_filter']['enabled']:
        lines.append('Project scope: project directory and descendants only (based on log cwd).')
    task_filters = report.get('task_filters', {})
    if any(task_filters.values()):
        lines.append('Task evidence filter: ' + ' · '.join(
            f'{label}={task_filters[key]}' for key, label in
            (('model', 'model'), ('reasoning_effort', 'effort')) if task_filters.get(key))
            + ' (does not change the historical L0–L7 level)')
    if report['note']:
        lines.append(report['note'])
    visibility = report.get('level_visibility', {})
    if visibility.get('may_undercount_edits_and_verification'):
        lines.append(f"Code orchestration calls {visibility['opaque_orchestrator_calls']} have no complete nested tool trace. "
                     "Log levels may undercount edits and verification. See the Anthropic evaluation for task acceptance results.")
    observed = report['observed']
    lines.extend(['', heading('Observed')])
    for label, key in [('Human inputs', 'humanish_user'), ('Tool calls', 'tool_calls'),
                       ('Edit calls', 'edit_calls'), ('Edit → verify sessions', 'engineering_sessions'),
                       ('Engineering days', 'engineering_days'), ('Tool / human', 'tool_per_human')]:
        lines.append(f"- {label}: {observed[key]}")
    coverage = report.get('verification_coverage', {})
    if coverage:
        lines.extend(['', heading('Final edit verification coverage'),
                      f"Edited sessions: {coverage['edited_sessions']}; verification after final observed edit: "
                      f"{coverage['final_edit_verified_sessions']} ({num(coverage['final_edit_verification_coverage'], '{:.1%}')})",
                      f"Latest verification results: passed {coverage['final_edit_verification_passed_sessions']} / "
                      f"failed {coverage['final_edit_verification_failed_sessions']} / "
                      f"unknown {coverage['final_edit_verification_unknown_sessions']}",
                      f"No verification after final edit: {coverage['final_edit_without_verification_sessions']}; "
                      f"unknown event order: {coverage['final_edit_order_unknown_sessions']}",
                      coverage['note']])
        for category, counts in coverage['categories'].items():
            lines.append(f"- {category}: attempts {counts['attempts']} / passed {counts['passed']} / "
                         f"failed {counts['failed']} / unknown {counts['unknown']}")
    visibility = report.get('tool_observability', {})
    if visibility:
        lines.extend(['', heading('Tool observability'),
                      f"Recognized tool calls: {visibility['recognized_tool_calls']}; "
                      f"structured nested calls: {visibility['structured_nested_tool_calls']}; "
                      f"public JSONL calls: {visibility['public_jsonl_tool_calls']}",
                      f"Orchestration: expanded {visibility['expanded_orchestrator_calls']} / "
                      f"opaque {visibility['opaque_orchestrator_calls']}; "
                      f"expansion coverage {num(visibility['orchestrator_expansion_ratio'], '{:.1%}')}",
                      f"Unparsed records: {visibility.get('unparsed_records', 0)}; "
                      f"missing timestamp records: {visibility.get('missing_timestamp_records', 0)}",
                      visibility['note']])
    usage = report.get('model_usage', {})
    if usage.get('roles'):
        lines.extend(['', heading('Token usage by role')])
        for row in usage['roles']:
            lines.append(f"- {row['source']} / {row['role']}: total {row['total_tokens']}; "
                         f"uncached input {row['uncached_input_tokens']}; cache read {row['cache_read']}; "
                         f"cache write {row['cache_creation']}; output {row['output_tokens']}; "
                         f"reasoning subset {row['reasoning_output_tokens']} "
                         f"({row['reasoning_records']} usage records report reasoning)")
        lines.append('Token totals are input plus output, including cached input. Reasoning is an output subset. '
                     'Roles follow recorded metadata; unknown roles remain unknown. These counts are not monetary costs '
                     'and are not divided by unrelated task outcomes.')
    lines.extend(['', heading('Level gates')])
    for key, gate in report['levels'].items():
        title = LEVEL_SHORT.get(int(key[1:])) or f'{key} {LEVEL_NAMES[int(key[1:])]}'
        lines.append(f"{title} — {gate['status']}")
        for check in gate['checks']:
            mark = 'x' if check['pass'] else ' '
            lines.append(f"- [{mark}] {check['check']} ({check['detail']})")
    if report['gaps']:
        lines.extend(['', heading(f"{level_label(report['next_target'])} Gaps")])
        lines.extend('- ' + check['check'] for check in report['gaps'])
        experiment = recommended_experiment(report)
        if experiment:
            lines.extend(['', heading('Recommended experiment'), experiment, EXPERIMENT_NOTE])
    scope = report['scope']
    lines.extend(['', heading('Data quality'),
                  f"Session files: {scope['files_with_data']} / {scope['files_scanned']}",
                  f"Parse errors: {scope['parse_errors']} · Diagnostics: {scope['diagnostics']}",
                  '', render_summary(anthropic, markdown=markdown),
                  '', render_improvement(report['self_improvement_evaluation'], markdown=markdown),
                  '', heading('Limitations')])
    if any(key in scope['diagnostics'] for key in
           ('invalid_task_records', 'unreadable_task_records', 'oversized_task_records', 'invalid_task_stores')):
        lines.append(DISCOVERY_NOTE)
    lines.extend('- ' + note for note in report['limitations'])
    return '\n'.join(lines)


def build_report(m: Metrics, res: dict, since, until,
                 report_name=DEFAULT_REPORT_NAME, task_filters=None) -> dict:
    opaque_calls = m.diagnostics['opaque_orchestrator_calls']
    return {
        "version": VERSION,
        "report_name": report_name,
        "ruleset_version": RULESET_VERSION,
        "source": m.source,
        "sources": sorted(m.sources),
        "assessment_basis": res["basis"],
        "level_visibility": {
            "status": "partial" if opaque_calls else "direct",
            "opaque_orchestrator_calls": opaque_calls,
            "may_undercount_edits_and_verification": bool(opaque_calls),
        },
        "project_filter": {"enabled": m.project_filtered, "includes_descendants": m.project_filtered},
        "task_filters": task_filters or {"model": None, "reasoning_effort": None},
        "observed_level": res["observed_level"],
        "limitations": res["limitations"],
        "note": res["below_note"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window": window_str(m, since, until),
        "observed_window": {
            "since": m.first_ts.date().isoformat() if m.first_ts else None,
            "until": m.last_ts.date().isoformat() if m.last_ts else None,
            "timezone": "UTC",
        },
        "requested_window": {
            "since": since.date().isoformat() if since else None,
            "until": (until - timedelta(days=1)).date().isoformat() if until else None,
            "timezone": "UTC",
        },
        "current_level": res["current"],
        "current_level_name": LEVEL_NAMES[res["current"]],
        "next_target": res["next"],
        "long_target": 7,
        "long_target_note": "L7 is a specialized research direction, not an upgrade target for every engineering team.",
        "scope": {
            "files_scanned": m.files_scanned,
            "files_with_data": m.files_with_data,
            "records": m.records,
            "sessions": len(m.sessions),
            "active_days": len(m.days),
            "parse_errors": m.parse_errors,
            "diagnostics": dict(m.diagnostics),
        },
        "observed": {
            "humanish_user": m.humanish_user,
            "user_records": m.user_records,
            "assistant": m.assistant,
            "assistant_sidechain": m.assistant_sidechain,
            "tool_calls": m.tool_calls,
            "edit_calls": m.edit_calls,
            "engineering_sessions": len(m.engineering_sessions),
            "engineering_days": len(m.engineering_days),
            "tool_calls_sidechain": m.tool_calls_sidechain,
            "tool_per_human": round(m.tool_per_human, 3),
            "assistant_per_human": round(m.assistant_per_human, 3),
            "subagent_files": m.subagent_files,
            "workflow_calls": m.workflow_calls,
            "delegation_tool_calls": m.delegation_tool_calls,
            "cache_read": m.cache_read,
            "cache_creation": m.cache_creation,
            "output_tokens": m.output_tokens,
            "input_tokens": m.input_tokens,
            "cache_reuse": round(m.cache_reuse, 3) if m.cache_reuse is not None and m.sources == {"claude"} else None,
            "cache_hit_ratio": round(m.cache_read / m.input_tokens, 4) if m.input_tokens else None,
            "tools": dict(m.tools.most_common()),
            "bash": {c: m.bash[c] for c in BASH_CATEGORY_ORDER},
            "verification_calls": m.verification_calls,
            "verification_ratio": round(m.verification_ratio, 4),
        },
        "model_usage": usage_breakdown(m),
        "verification_coverage": verification_coverage(m),
        "tool_observability": observability(m),
        "stats_cache": {
            "source": "claude",
            "available": m.stats_available,
            "active_days": m.stats_days,
            "range": m.stats_window,
            "sessions": m.stats_sessions,
            "messages": m.stats_messages,
            "tool_calls": m.stats_tool_calls,
        },
        "levels": {
            f"L{lvl}": {
                "status": res["status"][lvl],
                "checks": [c.as_dict() for c in res["gates"][lvl]],
            } for lvl in range(8)
        },
        "gaps": [c.as_dict() for c in res["gaps"]],
        "human_input_filter": HUMAN_FILTER_RULES,
        "anthropic_evaluation": res.get('anthropic_evaluation') or assess_anthropic(m, since=since, until=until),
        "self_improvement_evaluation": res.get('self_improvement_evaluation') or assess_improvement(),
        "references": REFERENCES,
        "method_note": METHOD_NOTE,
    }


def build_parser():
    p = argparse.ArgumentParser(description="Agent Level — local Claude Code and Codex workflow assessment")
    p.add_argument("--source", choices=("claude", "codex", "all"), default="all")
    p.add_argument("--view", choices=("separate", "combined", "both"), default="both")
    p.add_argument("--claude-dir", default=os.environ.get("CLAUDE_DIR", "~/.claude"))
    p.add_argument("--codex-dir", default=os.environ.get("CODEX_HOME", "~/.codex"))
    p.add_argument("--project-dir", type=Path,
                   help="Analyze historical sessions in this project and its subdirectories using log cwd; does not run tasks")
    p.add_argument("--eval-results", type=Path,
                   help="Optional task evaluation JSON, possibly containing improvement_comparisons; does not run referenced files")
    p.add_argument("--evidence-root", type=Path,
                   help="Verify local evidence hashes, scores, and artifact links in this directory; requires --eval-results")
    p.add_argument("--eval-k", type=int, default=3,
                   help="k for pass@k / pass^k; default 3; a statistical parameter, not an official threshold")
    p.add_argument("--model", help="Filter task evaluation records by model (not historical L0-L7 logs)")
    p.add_argument("--reasoning-effort", "--effort", dest="reasoning_effort",
                   help="Filter task evaluation records by effort; legacy missing values use documented model defaults")
    p.add_argument("--no-auto-evals", action="store_true",
                   help="In project mode, analyze historical logs without reading task evaluation records")
    p.add_argument("--format", choices=("txt+html", "txt", "text", "md", "json", "html"),
                   default="html", help="Default html (one file); txt+html writes both; text is an alias for txt")
    p.add_argument("--report-name", "--name", default=DEFAULT_REPORT_NAME,
                   help="Report title and, without -o, the output filename")
    p.add_argument("--output", "-o", type=Path,
                   help="Output path; default out/agent_level/YYYY-MM-DD/<report-name>.<format> (local date); dual format replaces suffix; - writes one format to stdout")
    p.add_argument("--since", metavar="YYYY-MM-DD", help="First UTC date, inclusive")
    p.add_argument("--until", metavar="YYYY-MM-DD", help="Last UTC date, inclusive")
    p.add_argument("--days", type=int, metavar="N", help="Last N UTC calendar days, including today")
    p.add_argument("--version", action="version", version=VERSION)
    return p


def main(argv=None, *, default_method='levels') -> int:
    args = build_parser().parse_args(argv)
    report_name = args.report_name.strip()
    stem = report_stem(report_name)
    if not report_name or not stem:
        print("[error] --report-name must contain letters or numbers", file=sys.stderr)
        return 2
    formats = ("txt", "html") if args.format == "txt+html" else (
        "txt" if args.format == "text" else args.format,
    )
    if args.output == Path("-") and len(formats) > 1:
        print("[error] stdout requires a single --format (txt, html, md or json)", file=sys.stderr)
        return 2
    since = until = None
    try:
        if args.days is not None:
            if args.since or args.until or args.days < 1:
                raise ValueError("--days must be >= 1 and cannot be combined with --since/--until")
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            since = today - timedelta(days=args.days - 1)
            until = today + timedelta(days=1)
        else:
            since = parse_date(args.since) if args.since else None
            until = parse_date(args.until) + timedelta(days=1) if args.until else None
            if since and until and since >= until:
                raise ValueError("--since must not be after --until")
    except (ValueError, OverflowError) as exc:
        print(f"[error] bad date: {exc}", file=sys.stderr)
        return 2
    project_dir = args.project_dir.expanduser().resolve() if args.project_dir else None
    if project_dir is not None and not project_dir.is_dir():
        print('[error] --project-dir must be an existing directory', file=sys.stderr)
        return 2
    if args.no_auto_evals and args.eval_results is not None:
        print('[error] --no-auto-evals cannot be combined with --eval-results', file=sys.stderr)
        return 2
    if project_dir is not None and args.eval_results is not None:
        print('[error] --project-dir filters historical logs; task imports cannot be filtered by project; run --eval-results separately', file=sys.stderr)
        return 2
    if args.eval_k < 1:
        print("[error] --eval-k must be >= 1", file=sys.stderr)
        return 2
    if any(value is not None and not value.strip() for value in (args.model, args.reasoning_effort)):
        print('[error] --model and --effort must not be empty', file=sys.stderr)
        return 2
    discovery = {'enabled': project_dir is not None and not args.no_auto_evals, 'files': 0, 'tasks': 0}
    try:
        show_progress("Reading task evaluation records…")
        eval_data = load_evals(args.eval_results.expanduser() if args.eval_results else None)
        if args.evidence_root and args.eval_results is None:
            raise ValueError("--evidence-root requires --eval-results")
        evidence_reader = EvidenceReader(args.evidence_root.expanduser()) if args.evidence_root else None
        if discovery['enabled']:
            from assessment.collection import load_project_evals
            eval_data, evidence_reader, counts = load_project_evals(project_dir)
            discovery.update(counts)
        eval_data = filter_evals(eval_data, args.model, args.reasoning_effort)
    except (ValueError, OSError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    if discovery['enabled']:
        show_progress(f"Found {discovery['files']} project task records covering {discovery['tasks']} tasks")
        if discovery.get('diagnostics'):
            print('[warn] ' + DISCOVERY_NOTE, file=sys.stderr)
    sources = ("claude", "codex") if args.source == "all" else (args.source,)
    collected = {}
    for source in sources:
        root = Path(getattr(args, source + "_dir")).expanduser()
        if not root.is_dir():
            print(f"[warn] {source} data directory not found", file=sys.stderr)
            collected[source] = Metrics(source)
            collected[source].project_filtered = project_dir is not None
            continue
        show_progress(f"Scanning {source} session logs…")
        started = time.monotonic()
        collected[source] = (scan if source == "claude" else scan_codex)(
            root, since, until, project_dir=project_dir, progress=scan_progress(source))
        metrics = collected[source]
        show_progress(f"{source} scan complete: {metrics.files_scanned} files, "
                      f"{metrics.files_with_data} with data in the selected range, "
                      f"{time.monotonic() - started:.1f} seconds")
    selected = {}
    if args.view in ("combined", "both") and args.source == "all":
        selected["combined"] = merge_metrics(collected.values())
    if args.view in ("separate", "both") or args.source != "all":
        selected.update(collected)
    reports = {}
    task_filters = {'model': args.model, 'reasoning_effort': args.reasoning_effort}
    for name, metrics in selected.items():
        show_progress(f"Calculating {name} assessment…")
        metrics.diagnostics.update(discovery.get('diagnostics', {}))
        result = evaluate(metrics)
        result['anthropic_evaluation'] = assess_anthropic(metrics, eval_data, since, until, args.eval_k, evidence_reader)
        result['self_improvement_evaluation'] = assess_improvement(
            eval_data, evidence_reader, metrics.sources, since, until)
        reports[name] = build_report(metrics, result, since, until, report_name, task_filters)
    for line in render_key_metrics(reports).splitlines():
        show_progress(line)
    download_stem = args.output.stem if args.output and args.output != Path("-") else stem
    bundle = {"version": VERSION, "ruleset_version": RULESET_VERSION,
              "view": args.view, "report_name": report_name,
              "report_file_stem": download_stem, "reports": reports,
              "project_task_records": discovery,
              "task_filters": task_filters,
              "evaluation_methods": ["level_assessment_l0_l7", "anthropic_evals", "self_improvement_comparison"],
              "references": REFERENCES, "method_note": METHOD_NOTE,
              "merge_note": "Counts are merged before ratios are recalculated, and active dates are unioned. Edit/verification chains are not joined across sources, and cross-source tasks are not deduplicated."}
    output_base = args.output or (
        Path("out") / "agent_level" / datetime.now().strftime("%Y-%m-%d") / stem
    )
    try:
        for fmt in formats:
            show_progress(f"Generating {fmt.upper()} report…")
            if fmt == "html":
                from assessment.web import render_html
                out = render_html(bundle, default_method=default_method)
            elif fmt == "json":
                out = json.dumps(bundle, ensure_ascii=False, indent=2)
            else:
                out = "\n\n".join(render_report(report, markdown=fmt == "md") for report in reports.values())
            if args.output == Path("-"):
                print(out)
                continue
            output_path = output_base.expanduser()
            if args.output is None or len(formats) > 1:
                output_path = output_path.with_suffix(f".{fmt}")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(out + "\n", encoding="utf-8")
            absolute_path = output_path.resolve()
            if fmt == "html":
                print(f"[open in browser] {absolute_path.as_uri()}", file=sys.stderr)
            else:
                print(f"[ok] report written: {absolute_path}", file=sys.stderr)
    except OSError:
        print("[error] cannot write report", file=sys.stderr)
        return 2
    return 0


def cli(argv=None, *, default_method='levels'):
    try:
        return main(argv, default_method=default_method)
    except BrokenPipeError:
        os._exit(0)
    except KeyboardInterrupt:
        return 130


def project_cli(argv=None, *, default_method='levels'):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not any(arg in ("--project-dir", "--eval-results") or
               arg.startswith(("--project-dir=", "--eval-results=")) for arg in argv):
        argv = ["--project-dir", str(Path.cwd()), *argv]
    return cli(argv, default_method=default_method)


if __name__ == "__main__":
    sys.exit(project_cli())
