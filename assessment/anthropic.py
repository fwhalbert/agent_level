"""Evidence-based summaries of imported eval trials; never infer outcomes from logs.

This is a local implementation of Anthropic's published methodology, not an
official Anthropic scoring standard or an evaluation execution harness.
"""
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .history import render_history
from .references import ANTHROPIC_URL, METHOD_NOTE

SCHEMA_VERSION = '1.0'
IDENTITY = ('source', 'suite_id', 'suite_version', 'model', 'harness_version', 'task_id')
# Defaults for legacy records that omitted effort. Keep this list narrow: unknown
# models have no defensible inferred effort. Explicit "unknown" is not backfilled.
# https://developers.openai.com/api/docs/guides/reasoning
# https://platform.claude.com/docs/en/build-with-claude/effort
OFFICIAL_DEFAULT_EFFORT = {
    ('codex', 'gpt-6-sol'): 'medium',
    ('codex', 'gpt-6-luna'): 'medium',
    ('codex', 'gpt-5.5'): 'medium',
    ('codex', 'gpt-5.6'): 'medium',
    ('claude', 'claude-opus-5-5'): 'medium',
    ('claude', 'opus 5.5'): 'medium',
    ('claude', 'opus 5.5 (1m context)'): 'medium',
    ('claude', 'claude-opus-5'): 'high',
    ('claude', 'opus 5'): 'high',
    ('claude', 'claude-sonnet-5'): 'high',
}
STEPS = [
    ('task', 'Task and success criteria', 'Define task, acceptance criteria, and planned graders; controlled evaluations also need a reference solution.'),
    ('trial', 'Independent trials and environment', 'Record trial, time, and runtime version; environment reset is required only for controlled evaluations.'),
    ('transcript', 'Execution trace', 'Keep a traceable transcript; session count cannot replace trial count.'),
    ('grader', 'Grader evidence', 'Every required grader needs a result and evidence reference; model graders also need a human calibration reference.'),
    ('outcome', 'Final outcome', 'Record the final outcome and acceptance evidence; a test call or agent claim cannot replace them.'),
    ('repeat', 'Repeat reliability', 'Repeat trials under the same task, source, model, effort, harness, and suite version.'),
    ('audit', 'Human review', 'Record human review of task/graders and transcript; a reference alone is not an independent audit.'),
]
REASONS = {
    'acceptance_failed': 'Acceptance failed', 'missing_or_inconsistent_evidence': 'Grading missing or inconsistent',
    'execution_incomplete': 'Execution incomplete / interrupted', 'conflicting_record': 'Conflicting record',
    'conflicting_task': 'Conflicting task definition', 'evidence_verification_failed': 'Local evidence verification failed',
    'invalid_record': 'Invalid trial record', 'outside_window': 'Trial outside selected period',
}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def task_effort(task):
    """Use recorded effort, or a documented model default for older records."""
    effort = task.get('reasoning_effort')
    if effort is not None:
        return effort.strip().lower() if _text(effort) else 'unknown'
    model = task.get('model')
    if not _text(model):
        return 'unknown'
    return OFFICIAL_DEFAULT_EFFORT.get((task.get('source'), model.strip().lower()), 'unknown')


def filter_evals(data, model=None, effort=None):
    """Select imported task evidence without changing the original task objects."""
    if data is None or (model is None and effort is None):
        return data

    def matches(item):
        return (isinstance(item, dict)
                and (model is None or (isinstance(item.get('model'), str)
                                       and item['model'].strip().casefold() == model.strip().casefold()))
                and (effort is None or task_effort(item) == effort.strip().casefold()))

    selected = dict(data)
    selected['tasks'] = [task for task in data['tasks'] if matches(task)]
    if isinstance(data.get('improvement_comparisons'), list):
        selected['improvement_comparisons'] = [item for item in data['improvement_comparisons'] if matches(item)]
    return selected


def _timestamp(value):
    if not _text(value):
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        # Unlike legacy logs, imported trials must identify a timezone.
        return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def load_evals(path):
    """Read only the explicitly supplied JSON; never follow evidence references."""
    if path is None:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError):
        raise ValueError('Cannot read evaluation results (expected a UTF-8 JSON file)') from None
    if (not isinstance(data, dict) or data.get('schema_version') not in ('1.0', '1.1')
            or not isinstance(data.get('tasks'), list)):
        raise ValueError('Evaluation results require schema_version="1.0" or "1.1" and a tasks array')
    return data


def _task_ready(task):
    required = task.get('required_graders')
    return (all(_text(task.get(key)) for key in IDENTITY)
            and _text(task.get('acceptance_criteria'))
            and (task.get('evaluation_mode') == 'daily' or _text(task.get('reference_solution_ref')))
            and isinstance(required, list) and bool(required)
            and all(_text(item) for item in required)
            and len(set(required)) == len(required)
            and type(task.get('planned_trials')) is int and task['planned_trials'] > 0
            and (task.get('evaluation_mode') != 'daily' or task['planned_trials'] == 1))


def _trial_evidence(task, trial):
    trial_ok = (_text(trial.get('trial_id')) and _timestamp(trial.get('timestamp')) is not None
                and (task.get('evaluation_mode') == 'daily' or trial.get('environment_reset') is True))
    transcript = _text(trial.get('transcript_ref'))
    graders = trial.get('graders')
    grader_ok = isinstance(graders, list) and bool(graders) and _task_ready(task)
    if grader_ok:
        ids = [g.get('grader_id') for g in graders if isinstance(g, dict)]
        grader_ok = (len(ids) == len(graders) and all(_text(i) for i in ids)
                     and len(set(ids)) == len(ids) and set(ids) == set(task['required_graders']))
        grader_ok = grader_ok and all(
            g.get('type') in ('code', 'model', 'human')
            and type(g.get('passed')) is bool and _text(g.get('evidence_ref'))
            and (g['type'] != 'model' or _text(g.get('human_calibration_ref')))
            for g in graders)
    outcome = trial.get('outcome')
    outcome_ok = (isinstance(outcome, dict) and type(outcome.get('passed')) is bool
                  and _text(outcome.get('evidence_ref')))
    consistent = (grader_ok and outcome_ok
                  and outcome['passed'] == all(g['passed'] for g in graders))
    checks = {'task': _task_ready(task), 'trial': trial_ok, 'transcript': transcript,
              'grader': bool(grader_ok), 'outcome': bool(outcome_ok and consistent),
              'audit': _text(task.get('review_ref')) and _text(trial.get('review_ref'))}
    # Manual review is tracked separately; not every trial needs a human grader.
    eligible = all(checks[key] for key in ('task', 'trial', 'transcript', 'grader', 'outcome'))
    return checks, outcome['passed'] if eligible else None


def _rates(n, c, k):
    """Finite-sample, without-replacement estimates for a single task."""
    at = 1.0 if n - c < k else 1 - math.prod((n - c - i) / (n - i) for i in range(k))
    power = 0.0 if c < k else math.prod((c - i) / (n - i) for i in range(k))
    return at, power


def _wilson(success, total):
    if not total:
        return None
    z = 1.959963984540054
    p = success / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, center - margin), min(1.0, center + margin)]


def assess(metrics, data=None, since=None, until=None, k=3, evidence_reader=None):
    if type(k) is not int or k < 1:
        raise ValueError('eval k must be a positive integer')
    counts, diagnostics, checks, reasons = Counter(), Counter(), Counter(), Counter()
    groups = defaultdict(list)
    records, conflicting = {}, set()
    for task in data['tasks'] if data else []:
        if not isinstance(task, dict) or task.get('source') not in ('claude', 'codex'):
            diagnostics['invalid_tasks'] += 1
            continue
        if task['source'] not in metrics.sources:
            continue
        if (not all(_text(task.get(key)) for key in IDENTITY)
                or task.get('evaluation_mode', 'controlled') not in ('daily', 'controlled')):
            diagnostics['invalid_tasks'] += 1
            continue
        key = ((task.get('evaluation_mode', 'controlled'),)
               + tuple(task[field] for field in IDENTITY[:-1])
               + (task_effort(task), task['task_id']))
        if key in records:
            if records[key] == task:
                diagnostics['duplicate_tasks'] += 1
            else:
                conflicting.add(key)
                diagnostics['conflicting_tasks'] += 1
            continue
        records[key] = task

    dates = []
    for key, task in records.items():
        mode = key[0]
        raw_trials = task.get('trials')
        invalid = 0
        if not isinstance(raw_trials, list):
            diagnostics['invalid_trial_lists'] += 1
            raw_trials = []
        unique, conflict_ids = {}, set()
        for trial in raw_trials:
            if not isinstance(trial, dict) or not _text(trial.get('trial_id')):
                diagnostics['invalid_trials'] += 1
                invalid += 1
                continue
            tid = trial['trial_id']
            if tid in unique:
                if unique[tid] == trial:
                    diagnostics['duplicate_trials'] += 1
                else:
                    diagnostics['conflicting_trials'] += 1
                    conflict_ids.add(tid)
            else:
                unique[tid] = trial
        planned = task.get('planned_trials')
        valid_plan = type(planned) is int and planned > 0
        expected = max(planned if valid_plan else 0, len(unique) + invalid, 1)
        outside = sum(1 for t in unique.values() if _timestamp(t.get('timestamp')) is not None
                      and ((since and _timestamp(t['timestamp']) < since)
                           or (until and _timestamp(t['timestamp']) >= until)))
        # A wholly dated, out-of-window task is not part of this report.
        # Missing or unexecuted records cannot vanish through date filtering.
        if outside == len(unique) and unique and not invalid and expected == len(unique):
            continue
        ready = _task_ready(task)
        counts['tasks'] += 1
        counts['defined_tasks'] += int(ready)
        counts['expected_trials'] += expected
        outcomes = []
        unknown = invalid + outside
        not_run = max(0, expected - len(unique) - invalid)
        counts['outside_window_trials'] += outside
        reasons['invalid_record'] += invalid
        reasons['outside_window'] += outside
        verified = 0
        durations, interventions = [], []
        for tid, trial in unique.items():
            ts = _timestamp(trial.get('timestamp'))
            if ts and ((since and ts < since) or (until and ts >= until)):
                continue
            counts['trials'] += 1
            if trial.get('transcript_kind') == 'collector_journal':
                counts['collector_journal_trials'] += 1
            elif trial.get('transcript_kind') == 'session_export':
                counts['session_export_trials'] += 1
            if ts:
                dates.append(ts.date().isoformat())
            else:
                diagnostics['invalid_timestamps'] += 1
            flags, passed = _trial_evidence(task, trial)
            checks.update({name: int(value) for name, value in flags.items()})
            reason = None
            if key in conflicting or tid in conflict_ids:
                passed, reason = None, 'conflicting_record'
            elif trial.get('status') in ('running', 'grading', 'interrupted', 'error'):
                passed, reason = None, 'execution_incomplete'
            elif passed is None:
                reason = 'missing_or_inconsistent_evidence'
            if passed is not None and evidence_reader is not None:
                ok, reason = evidence_reader.verify_trial(trial)
                if ok:
                    verified += 1
                else:
                    passed = None
                    diagnostics['evidence_verification_failed'] += 1
            if passed is None:
                unknown += 1
                reasons[reason or 'missing_or_inconsistent_evidence'] += 1
            else:
                outcomes.append(passed)
                if not passed:
                    reasons['acceptance_failed'] += 1
            for field, dest in (('duration_seconds', durations), ('human_interventions', interventions)):
                value = trial.get(field)
                if type(value) in (int, float) and math.isfinite(value) and value >= 0:
                    dest.append(value)
        if key in conflicting:
            # A task-level conflict may also concern the declared plan.
            reasons['conflicting_task'] += 1
        success, graded = sum(outcomes), len(outcomes)
        complete = (ready and key not in conflicting and not unknown and not not_run
                    and valid_plan and graded == planned)
        row = {'expected': expected, 'success': success, 'failure': graded - success,
               'unknown': unknown, 'not_run': not_run, 'complete': complete,
               'graded': graded, 'verified': verified, 'durations': durations, 'interventions': interventions}
        groups[key[:-1]].append(row)
        counts.update(graded_trials=graded, successful_trials=success, failed_trials=graded-success,
                      unknown_trials=unknown, not_run_trials=not_run, verified_trials=verified,
                      complete_tasks=int(complete),
                      repeated_tasks=int(complete and mode == 'controlled' and graded >= k))

    group_reports = []
    for index, (key, tasks) in enumerate(sorted(groups.items()), 1):
        mode = key[0]
        complete = [t for t in tasks if t['complete']]
        repeated = [t for t in complete if t['graded'] >= k] if mode == 'controlled' else []
        all_complete = len(complete) == len(tasks)
        repeated_complete = all_complete and len(repeated) == len(tasks)
        estimates = [_rates(t['graded'], t['success'], k) for t in repeated] if repeated_complete else []
        sums = {field: sum(t[field] for t in tasks)
                for field in ('expected', 'success', 'failure', 'unknown', 'not_run', 'graded', 'verified')}
        lower = sum(t['success'] / t['expected'] for t in tasks) / len(tasks)
        upper = sum((t['success'] + t['unknown'] + t['not_run']) / t['expected'] for t in tasks) / len(tasks)
        durations = [v for t in tasks for v in t['durations']]
        interventions = [v for t in tasks for v in t['interventions']]
        group_reports.append({
            'label': f'Evaluation group {index}', 'source': key[1], 'evaluation_mode': mode, 'tasks': len(tasks),
            'complete_tasks': len(complete), 'repeated_tasks': len(repeated), 'outcomes': sums,
            'coverage': sums['graded'] / sums['expected'],
            'observed_success_rate': sums['success'] / sums['graded'] if sums['graded'] else None,
            'success_bounds': [lower, upper],
            'daily_success_rate': lower if mode == 'daily' and all_complete else None,
            'daily_wilson_95': _wilson(sums['success'], sums['graded']) if mode == 'daily' and all_complete else None,
            'pass_at_1': lower if mode == 'controlled' and all_complete else None,
            'pass_at_k': sum(r[0] for r in estimates) / len(estimates) if estimates else None,
            'pass_power_k': sum(r[1] for r in estimates) / len(estimates) if estimates else None,
            'duration_seconds': {'recorded': len(durations), 'total': sum(durations)},
            'human_interventions': {'recorded': len(interventions), 'total': sum(interventions)},
        })
    count_keys = ('tasks', 'defined_tasks', 'trials', 'expected_trials', 'graded_trials', 'successful_trials',
                  'failed_trials', 'unknown_trials', 'not_run_trials', 'verified_trials', 'outside_window_trials',
                  'complete_tasks', 'repeated_tasks', 'collector_journal_trials', 'session_export_trials')
    state = ('imported_results' if counts['tasks'] and counts['tasks'] == counts['complete_tasks'] and not diagnostics['invalid_tasks']
             else 'partial_evidence' if counts['graded_trials'] else 'insufficient_evidence')
    readiness = []
    for name, label, need in STEPS:
        if name == 'task':
            have, total = counts['defined_tasks'], counts['tasks']
        elif name == 'repeat':
            have = counts['repeated_tasks']
            total = sum(len(rows) for key, rows in groups.items() if key[0] == 'controlled')
        else:
            have, total = checks[name], counts['expected_trials']
        readiness.append({'id': name, 'label': label, 'requirement': need,
                          'present': have, 'total': total,
                          'status': 'recorded' if total and have == total else 'partial' if have else 'missing'})
    return {
        'method': 'anthropic_evals', 'method_version': '1.1', 'reference_url': ANTHROPIC_URL,
        'status': state, 'status_label': {'imported_results': 'Task results available · Check evidence coverage',
                                        'partial_evidence': 'Partial evidence · Available results retained',
                                        'insufficient_evidence': 'Insufficient evidence · Task capability cannot be determined'}[state],
        'official_certification': False, 'synthetic': bool(data and data.get('synthetic') is True),
        'evidence_basis': 'local_checked' if evidence_reader is not None else 'imported' if data is not None else 'logs_only',
        'k': k, 'counts': {name: counts[name] for name in count_keys},
        'groups': group_reports, 'readiness': readiness,
        'diagnostics': {key: value for key, value in diagnostics.items() if value},
        'failure_reasons': {key: value for key, value in reasons.items() if value},
        'trial_window': {'since': min(dates) if dates else None, 'until': max(dates) if dates else None},
        'historical_activity': dict(metrics.history.summary(),
                                    opaque_orchestrator_calls=metrics.diagnostics.get('opaque_orchestrator_calls', 0)),
        'log_context': {'sessions': len(metrics.sessions), 'tool_calls': metrics.tool_calls,
                        'verification_attempts': metrics.verification_calls},
        'limitations': [METHOD_NOTE,
            'The collected event journal covers registration, notes, and acceptance, not the full session. Local consistency checks do not prove that the agent-defined criteria cover every requirement.',
            'Daily tasks record one acceptance run. Only controlled evaluations calculate pass@k / pass^k; the modes are not ranked together.',
            'Local verification checks file hashes, grader content, and artifact links in the selected directory. It is not an independent audit or a check of requirement coverage.',
            'The graded pass rate describes only trials with results. Success bounds include unknown and unrun trials in the denominator; they are not confidence intervals.',
            'Repeat probabilities are calculated only for complete controlled groups. Missing or conflicting records are isolated, while other evidence is kept. Invalid unassigned tasks are diagnosed separately and excluded from group denominators.',
            'Groups are separated by source, mode, suite/version, model, effort, and harness. Bounds and repeat probabilities weight tasks equally.',
            'Complete daily groups include a 95% Wilson interval, assuming independent outcomes sampled from a common success probability. It does not remove task selection bias.',
            'Out-of-window trials count as unknown in the planned denominator and are listed separately. Date filters do not remove unrun plans.',
            'Log counts, self-reported settings, and reference links are not success evidence. Historical logs cannot create independent repeat trials retroactively.',
        ],
    }

def render_summary(report, markdown=False):
    c = report['counts']
    lines = [('## ' if markdown else '') + 'Anthropic evaluation methodology', '', report['status_label'],
             f"Tasks {c['tasks']} · Complete tasks {c['complete_tasks']} · Trials {c['trials']} · Trials with grader evidence {c['graded_trials']}",
             'This method does not assign an L0–L7 level; evidence checks are not an independent audit.']
    if report.get('historical_activity', {}).get('sessions'):
        lines.extend(['', render_history(report['historical_activity']), ''])
    if report.get('synthetic'):
        lines.append('Synthetic example data illustrates the format and statistics; it does not represent real capability.')
    lines.append(f"Success {c['successful_trials']} / failure {c['failed_trials']} / unknown {c['unknown_trials']} / unrun {c['not_run_trials']}; Local evidence verification {c['verified_trials']} runs")
    if c.get('collector_journal_trials') or c.get('session_export_trials'):
        lines.append(f"Trace coverage: collector journal {c.get('collector_journal_trials', 0)} runs; session export {c.get('session_export_trials', 0)} runs. An event journal is not a full session transcript.")
    for group in report['groups']:
        fmt = lambda value: 'Insufficient evidence' if value is None else f'{value:.1%}'
        if group['evaluation_mode'] == 'daily':
            lines.append(f"{group['label']} ({group['source']}, daily): One acceptance run per daily task; pass@k / pass^k are not calculated")
        else:
            lines.append(f"{group['label']} ({group['source']}, controlled): pass@1={fmt(group['pass_at_1'])}, "
                         f"pass@{report['k']}={fmt(group['pass_at_k'])}, pass^{report['k']}={fmt(group['pass_power_k'])}")
        lines.append(f"Grading coverage={fmt(group['coverage'])}; Graded pass rate={fmt(group['observed_success_rate'])}; Planned success bounds={fmt(group['success_bounds'][0])} .. {fmt(group['success_bounds'][1])}")
        if group['evaluation_mode'] == 'daily':
            lines.append(f"Daily acceptance pass rate={fmt(group['daily_success_rate'])}; 95% Wilson interval={group['daily_wilson_95']}")
    if report['failure_reasons']:
        lines.append('Failure and missing evidence reasons: ' + '; '.join(
            f"{REASONS.get(reason, reason)}: {count}"
            for reason, count in report['failure_reasons'].items()))
    for row in report['readiness']:
        lines.append(f"- {row['label']}: {row['present']}/{row['total']}; {row['requirement']}")
    for note in report['limitations']:
        lines.append('- ' + note)
    if report['diagnostics']:
        lines.append('Import diagnostics: ' + json.dumps(report['diagnostics'], ensure_ascii=False))
    lines.append('Published method: ' + ANTHROPIC_URL)
    return '\n'.join(lines)
