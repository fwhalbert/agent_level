#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
assess.py — Local AI Engineering Assessment

Specification: docs/AGENT_LEVEL_L0-L7.md

Reads:
    <claude-dir>/projects/**/*.jsonl
    <claude-dir>/stats-cache.json
    <codex-dir>/sessions/**/*.jsonl
    <codex-dir>/archived_sessions/**/*.jsonl
    ai-level-evidence.json            (optional self-reported L5+ evidence)

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
    agent-level-assess --init-config
    agent-level-assess --config ai-level-evidence.json
    agent-level-assess --since 2026-09-01 --until 2026-09-20
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assessment.logs import (
    Metrics, scan, scan_codex, merge_metrics, parse_date, classify_bash,
    is_human_input, BASH_CATEGORY_ORDER,
    HUMAN_FILTER_RULES, DELEGATION_TOOLS, usage_breakdown,
)

from assessment.anthropic import assess as assess_anthropic, filter_evals, load_evals, render_summary
from assessment.improvement import assess as assess_improvement, render_summary as render_improvement
from assessment.references import REFERENCES, METHOD_NOTE
from assessment.evidence import EvidenceReader

VERSION = "2.4.0"
RULESET_VERSION = "2.0"
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
    None: "Insufficient evidence",
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

# L5 thresholds (specification section 4)
L5_MAX_INTERVENTIONS_PER_TASK = 1.0

# L5 / L6 / L7 evidence keys, in report order
L5_FLAGS = [
    ("persistent_task_pickup", "Persistent task pickup"),
    ("autonomous_pr", "Autonomous PR"),
    ("autonomous_ci_repair", "CI self-repair"),
    ("task_outcome_tracking", "Task outcome tracking"),
]
L5_NUMERIC = ("human_interventions_per_task", "Human interventions/task <= 1")

L6_FLAGS = [
    ("outcome_driven_improvement", "Outcome-driven improvement"),
    ("self_modify_prompts_tools_workflows", "Self-modify prompts/tools/workflows"),
    ("automated_eval_before_rollout", "Automated eval before rollout"),
    ("rollback_supported", "Rollback supported"),
]

L7_FLAGS = [
    ("autonomous_research_train_eval_deploy", "Autonomous research/train/eval/deploy"),
    ("next_generation_system_iteration", "Next-generation system iteration"),
    ("human_governance_gate", "Human governance gate"),
]

# --------------------------------------------------------------------------
# Evidence configuration (ai-level-evidence.json)
# --------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "_about": "L5–L7 self-reported evidence, not independently verified. In multi-source runs, top-level fields apply only to the combined view; put source-specific evidence under sources.claude or sources.codex.",
    "_docs": "docs/AGENT_LEVEL_L0-L7.md",
    "l5": {
        "persistent_task_pickup": False,
        "autonomous_pr": False,
        "autonomous_ci_repair": False,
        "task_outcome_tracking": False,
        "human_interventions_per_task": None,
    },
    "l6": {
        "outcome_driven_improvement": False,
        "self_modify_prompts_tools_workflows": False,
        "automated_eval_before_rollout": False,
        "rollback_supported": False,
    },
    "l7": {
        "autonomous_research_train_eval_deploy": False,
        "next_generation_system_iteration": False,
        "human_governance_gate": False,
    },
}

ALL_FLAG_KEYS = (
    [k for k, _ in L5_FLAGS] + [L5_NUMERIC[0]]
    + [k for k, _ in L6_FLAGS] + [k for k, _ in L7_FLAGS]
)


def load_config(path: Path | None, scope=None, allow_legacy=False) -> dict:
    """Flatten evidence from nested level groups or a flat mapping."""
    flat = {k: (None if k == L5_NUMERIC[0] else False) for k in ALL_FLAG_KEYS}
    if path is None:
        return flat
    if not path.is_file():
        print(f"[warn] config not found: {path}", file=sys.stderr)
        return flat
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as exc:
        print(f"[warn] cannot parse config ({exc.__class__.__name__}); ignored",
              file=sys.stderr)
        return flat
    if not isinstance(data, dict):
        return flat

    if scope is not None:
        if scope == "combined":
            data = data.get("combined", data)
        else:
            sources = data.get("sources", {})
            if "sources" in data or not allow_legacy:
                data = sources.get(scope, {}) if isinstance(sources, dict) else {}
        if not isinstance(data, dict):
            return flat

    def absorb(d):
        for k, v in d.items():
            if k in flat:
                if k == L5_NUMERIC[0]:
                    valid = v is None or (type(v) in (int, float) and math.isfinite(v) and v >= 0)
                else:
                    valid = type(v) is bool
                if valid:
                    flat[k] = v
                else:
                    print(f"[warn] invalid evidence field: {k}; ignored", file=sys.stderr)
    absorb(data)
    for section in ("l5", "l6", "l7", "L5", "L6", "L7"):
        sub = data.get(section)
        if isinstance(sub, dict):
            absorb(sub)
    return flat


def init_config(path: Path, force: bool) -> int:
    if path.exists() and not force:
        print(f"[skip] {path} already exists (use --force to overwrite)")
        return 1
    path.write_text(json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print(f"[ok] wrote {path}")
    print("     Edit the evidence fields, then run: "
          f"python3 {Path(sys.argv[0]).name} --config {path.name}")
    return 0


# --------------------------------------------------------------------------
# Assessment with cumulative gates (specification section 4)
# --------------------------------------------------------------------------

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


def evaluate(m: Metrics, cfg: dict) -> dict:
    """Ruleset 2: observed attempts up to L4, self-reported evidence above L4."""
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
    hipt = cfg.get(L5_NUMERIC[0])
    valid_rate = type(hipt) in (int, float) and math.isfinite(hipt) and 0 <= hipt <= L5_MAX_INTERVENTIONS_PER_TASK
    gates[5] = [Check(label, cfg.get(key) is True, "self-reported evidence")
                for key, label in L5_FLAGS]
    gates[5].append(Check(L5_NUMERIC[1], valid_rate,
                         num(hipt) if type(hipt) in (int, float) and math.isfinite(hipt) else "not recorded"))
    gates[6] = [Check(label, cfg.get(key) is True, "self-reported evidence") for key, label in L6_FLAGS]
    gates[7] = [Check(label, cfg.get(key) is True, "self-reported evidence") for key, label in L7_FLAGS]
    current = 2 if m.edit_calls else (1 if m.assistant or m.humanish_user or m.tool_calls else None)
    status, blocked = {}, False
    for level in (3, 4, 5, 6, 7):
        if not blocked and all(c.ok for c in gates[level]):
            current = level
            status[level] = "OBSERVED" if level <= 4 else "DECLARED"
        else:
            blocked = True
            status[level] = "NOT VERIFIED"
    observed = min(current, 4) if current is not None else None
    next_level = min(current + 1, 7) if current is not None else None
    gaps = [c for c in gates.get(next_level, []) if not c.ok] if next_level != current else []
    note = None
    if current is None:
        note = "Insufficient data. Missing logs do not imply L0; L0 requires human confirmation that AI did not perform engineering work."
    elif current == 1:
        note = "Only assistance or investigation was observed; these logs alone cannot distinguish L0 from L1."
    elif current == 2:
        note = "Code edits were observed, but the sample does not support L3; this is not a judgment of human ability."
    return {"gates": gates, "status": status, "current": current,
            "observed_level": observed, "next": next_level, "gaps": gaps,
            "below_note": note, "basis": "self-reported" if current and current >= 5 else "observed",
            "limitations": [
                "L0–L7 are project heuristics, not an industry certification or productivity ranking.",
                "L3/L4 are candidate levels based on log behavior; running a build/test after an edit does not prove it passed or that the task was completed.",
                "L5–L7 rely on self-reported evidence and need task outcomes, evaluations, and human audit.",
                "Message and tool formats vary by client; assistant/human and delegation counts are not hard thresholds.",
            ]}


def level_label(level):
    return "Unknown" if level is None else f"L{level}"


# --------------------------------------------------------------------------
# Report output (specification section 9)
# --------------------------------------------------------------------------

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
        lines.append(f"Code orchestration calls {visibility['opaque_orchestrator_calls']} have no visible nested tool trace. "
                     "Log levels may undercount edits and verification. See the Anthropic evaluation for task acceptance results.")
    observed = report['observed']
    lines.extend(['', heading('Observed')])
    for label, key in [('Human inputs', 'humanish_user'), ('Tool calls', 'tool_calls'),
                       ('Edit calls', 'edit_calls'), ('Edit → verify sessions', 'engineering_sessions'),
                       ('Engineering days', 'engineering_days'), ('Tool / human', 'tool_per_human')]:
        lines.append(f"- {label}: {observed[key]}")
    lines.extend(['', heading('Level gates')])
    for key, gate in report['levels'].items():
        lines.append(f"{LEVEL_SHORT[int(key[1:])]} — {gate['status']}")
        for check in gate['checks']:
            mark = 'x' if check['pass'] else ' '
            lines.append(f"- [{mark}] {check['check']} ({check['detail']})")
    if report['gaps']:
        lines.extend(['', heading(f"{level_label(report['next_target'])} Gaps")])
        lines.extend('- ' + check['check'] for check in report['gaps'])
    scope = report['scope']
    lines.extend(['', heading('Data quality'),
                  f"Session files: {scope['files_with_data']} / {scope['files_scanned']}",
                  f"Parse errors: {scope['parse_errors']} · Diagnostics: {scope['diagnostics']}",
                  '', render_summary(anthropic, markdown=markdown),
                  '', render_improvement(report['self_improvement_evaluation'], markdown=markdown),
                  '', heading('Limitations')])
    lines.extend('- ' + note for note in report['limitations'])
    return '\n'.join(lines)


def render_text(m: Metrics, res: dict, since, until, cfg_path) -> str:
    return render_report(build_report(m, res, since, until, cfg_path))


def render_md(m: Metrics, res: dict, since, until, cfg_path) -> str:
    return render_report(build_report(m, res, since, until, cfg_path), markdown=True)


def build_report(m: Metrics, res: dict, since, until, cfg_path,
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
        "evidence_config": cfg_path,
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
            } for lvl in (3, 4, 5, 6, 7)
        },
        "gaps": [c.as_dict() for c in res["gaps"]],
        "human_input_filter": HUMAN_FILTER_RULES,
        "anthropic_evaluation": res.get('anthropic_evaluation') or assess_anthropic(m, since=since, until=until),
        "self_improvement_evaluation": res.get('self_improvement_evaluation') or assess_improvement(),
        "references": REFERENCES,
        "method_note": METHOD_NOTE,
    }


def render_json(m: Metrics, res: dict, since, until, cfg_path) -> str:
    return json.dumps(build_report(m, res, since, until, cfg_path), indent=2, ensure_ascii=False)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(description="Claude + Codex AI Engineering Assessment")
    p.add_argument("--source", choices=("claude", "codex", "all"), default="all")
    p.add_argument("--view", choices=("separate", "combined", "both"), default="both")
    p.add_argument("--claude-dir", default=os.environ.get("CLAUDE_DIR", "~/.claude"))
    p.add_argument("--codex-dir", default=os.environ.get("CODEX_HOME", "~/.codex"))
    p.add_argument("--project-dir", type=Path,
                   help="Analyze historical sessions in this project and its subdirectories using log cwd; does not run tasks")
    p.add_argument("--config")
    p.add_argument("--eval-results", type=Path,
                   help="Optional task evaluation JSON, possibly containing improvement_comparisons; does not run referenced files")
    p.add_argument("--evidence-root", type=Path,
                   help="Verify local evidence hashes, scores, and artifact links in this directory; requires --eval-results")
    p.add_argument("--eval-k", type=int, default=3,
                   help="k for pass@k / pass^k; default 3; a statistical parameter, not an official threshold")
    p.add_argument("--model", help="Filter task evaluation records by model (not historical L0-L7 logs)")
    p.add_argument("--reasoning-effort", "--effort", dest="reasoning_effort",
                   help="Filter task evaluation records by effort; legacy missing values use documented model defaults")
    p.add_argument("--no-auto-config", action="store_true")
    p.add_argument("--no-auto-evals", action="store_true",
                   help="In project mode, analyze historical logs without reading task evaluation records")
    p.add_argument("--init-config", nargs="?", const="ai-level-evidence.json")
    p.add_argument("--force", action="store_true")
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


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    report_name = args.report_name.strip()
    stem = report_stem(report_name)
    if not report_name or not stem:
        print("[error] --report-name must contain letters or numbers", file=sys.stderr)
        return 2
    if args.init_config is not None:
        try:
            return init_config(Path(args.init_config).expanduser(), args.force)
        except OSError:
            print("[error] cannot write config", file=sys.stderr)
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
    if project_dir is not None and args.eval_results is not None:
        print('[error] --project-dir filters historical logs; task imports cannot be filtered by project; run --eval-results separately', file=sys.stderr)
        return 2
    cfg_path = Path(args.config).expanduser() if args.config else None
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
    if cfg_path is None and project_dir is None and not args.no_auto_config and Path("ai-level-evidence.json").is_file():
        cfg_path = Path("ai-level-evidence.json")
    sources = ("claude", "codex") if args.source == "all" else (args.source,)
    collected = {}
    for source in sources:
        root = Path(getattr(args, source + "_dir")).expanduser()
        if not root.is_dir():
            print(f"[warn] {source} data directory not found", file=sys.stderr)
            if eval_data is not None:
                collected[source] = Metrics(source)
                continue
            if args.source != "all":
                return 2
            continue
        show_progress(f"Scanning {source} session logs…")
        started = time.monotonic()
        collected[source] = (scan if source == "claude" else scan_codex)(
            root, since, until, project_dir=project_dir, progress=scan_progress(source))
        metrics = collected[source]
        show_progress(f"{source} scan complete: {metrics.files_scanned} files, "
                      f"{metrics.files_with_data} with data in the selected range, "
                      f"{time.monotonic() - started:.1f} seconds")
    if not collected:
        print("[error] no data directories found", file=sys.stderr)
        return 2
    selected = {}
    if args.view in ("combined", "both") and args.source == "all":
        selected["combined"] = merge_metrics(collected.values())
    if args.view in ("separate", "both") or args.source != "all":
        selected.update(collected)
    reports = {}
    shown_cfg = cfg_path.name if cfg_path else None
    task_filters = {'model': args.model, 'reasoning_effort': args.reasoning_effort}
    for name, metrics in selected.items():
        show_progress(f"Calculating {name} assessment…")
        config = load_config(cfg_path, scope=name, allow_legacy=args.source != "all")
        result = evaluate(metrics, config)
        result['anthropic_evaluation'] = assess_anthropic(metrics, eval_data, since, until, args.eval_k, evidence_reader)
        result['self_improvement_evaluation'] = assess_improvement(
            eval_data, evidence_reader, metrics.sources, since, until)
        reports[name] = build_report(metrics, result, since, until, shown_cfg, report_name, task_filters)
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
                out = render_html(bundle)
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
            print(f"[ok] report written: {absolute_path}", file=sys.stderr)
            if fmt == "html":
                print(f"[open in browser] {absolute_path.as_uri()}", file=sys.stderr)
    except OSError:
        print("[error] cannot write report", file=sys.stderr)
        return 2
    return 0


def cli(argv=None):
    try:
        return main(argv)
    except BrokenPipeError:
        os._exit(0)
    except KeyboardInterrupt:
        return 130


def project_cli():
    argv = sys.argv[1:]
    if not any(arg in ("--project-dir", "--eval-results") or
               arg.startswith(("--project-dir=", "--eval-results=")) for arg in argv):
        argv = ["--project-dir", str(Path.cwd()), *argv]
    return cli(argv)


if __name__ == "__main__":
    sys.exit(cli())
