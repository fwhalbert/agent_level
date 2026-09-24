"""Compare controlled before/after task results without trusting self-reported L6 flags.

This is an evidence consistency check, not an independent execution or a causal
claim. An assessor outside the improving agent must control the holdout suite,
the runs, and the evidence store for an independent assessment.
"""
import hashlib
import json
import math

from .anthropic import _task_ready, _trial_evidence, _timestamp, task_effort


FIELDS = ('source', 'suite_id', 'suite_version', 'model')
ARTIFACTS = ('plan', 'feedback', 'change', 'rollback')


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _cohort(task, reader, since, until):
    """Return task-level rates only when every planned trial is locally checked."""
    trials = task.get('trials')
    if (task.get('evaluation_mode', 'controlled') != 'controlled' or not _task_ready(task)
            or task['planned_trials'] < 3
            or not isinstance(trials, list) or len(trials) != task['planned_trials']
            or not all(isinstance(t, dict) and _nonempty(t.get('trial_id')) for t in trials)
            or len({t['trial_id'] for t in trials}) != len(trials)):
        return None
    outcomes, autonomous, grader_versions = [], [], None
    artifacts, traces = set(), set()
    for trial in trials:
        if (not isinstance(trial, dict) or trial.get('status') != 'completed'
                or trial.get('transcript_kind') != 'session_export'
                or trial.get('task_id') != task['task_id']):
            return None
        ts = _timestamp(trial.get('timestamp'))
        if ts is None or (since and ts < since) or (until and ts >= until):
            return None
        checks, passed = _trial_evidence(task, trial)
        if passed is None or not all(checks[key] for key in ('task', 'trial', 'transcript', 'grader', 'outcome')):
            return None
        interventions = trial.get('human_interventions')
        if type(interventions) not in (int, float) or not math.isfinite(interventions) or interventions < 0:
            return None
        artifact = trial.get('artifact_id')
        trace = trial.get('transcript_sha256')
        if (not _nonempty(artifact) or not _nonempty(trace)
                or artifact in artifacts or trace in traces):
            return None
        artifacts.add(artifact); traces.add(trace)
        versions = tuple(sorted((g['grader_id'], g.get('version')) for g in trial['graders']))
        if any(not _nonempty(version) for _, version in versions):
            return None
        if grader_versions is None:
            grader_versions = versions
        elif versions != grader_versions:
            return None
        if not reader.verify_trial(trial)[0]:
            return None
        try:
            evidence = [json.loads(reader.read(g['evidence_ref'], g['evidence_sha256']))
                        for g in trial['graders']]
            evidence.append(json.loads(reader.read(trial['outcome']['evidence_ref'],
                                                   trial['outcome']['evidence_sha256'])))
            if any(item.get('task_id') != task['task_id'] for item in evidence):
                return None
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return None
        outcomes.append(passed)
        autonomous.append(passed and interventions == 0)
    n = len(outcomes)
    return {'success': sum(outcomes) / n, 'autonomous': sum(autonomous) / n,
            'trials': n, 'grader_versions': grader_versions,
            'artifacts': artifacts, 'traces': traces}


def _sign_pvalue(positive, negative):
    """One-sided exact sign test over changed task-level autonomy rates."""
    n = positive + negative
    if not n:
        return None
    return sum(math.comb(n, i) for i in range(positive, n + 1)) / (2 ** n)


def _spec_digest(tasks):
    specs = [{field: task.get(field) for field in
              ('task_id', 'acceptance_criteria', 'reference_solution_ref',
               'required_graders', 'planned_trials')}
             for task in sorted(tasks, key=lambda item: item['task_id'])]
    raw = json.dumps(specs, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()


def assess(data=None, evidence_reader=None, sources=None, since=None, until=None):
    comparisons = data.get('improvement_comparisons', []) if isinstance(data, dict) else []
    if not isinstance(comparisons, list):
        return {'status': 'invalid_input', 'comparisons': [], 'diagnostics': {'invalid_comparisons': 1}}
    rows, diagnostics = [], {}
    tasks = data.get('tasks', []) if isinstance(data, dict) else []
    source_set = set(sources or ('claude', 'codex'))
    for comparison in comparisons:
        if not isinstance(comparison, dict) or comparison.get('source') not in ('claude', 'codex'):
            diagnostics['invalid_comparisons'] = diagnostics.get('invalid_comparisons', 0) + 1
            continue
        if comparison['source'] not in source_set:
            continue
        row = {'label': 'Improvement comparison ' + str(len(rows) + 1), 'source': comparison['source'],
               'status': 'insufficient_evidence', 'reason': None, 'tasks': 0, 'trials_per_variant': 0,
               'baseline_success': None, 'candidate_success': None, 'success_delta': None,
               'baseline_autonomous': None, 'candidate_autonomous': None, 'autonomous_delta': None,
               'improved_tasks': 0, 'regressed_tasks': 0, 'unchanged_tasks': 0, 'sign_test_p': None}
        rows.append(row)
        if data.get('synthetic') is True:
            row['reason'] = 'synthetic_data'
            continue
        if evidence_reader is None or not hasattr(evidence_reader, 'read'):
            row['reason'] = 'local_evidence_required'
            continue
        required = FIELDS + ('baseline_harness_version', 'candidate_harness_version', 'change_kind')
        if (not all(_nonempty(comparison.get(key)) for key in required)
                or comparison['baseline_harness_version'] == comparison['candidate_harness_version']
                or comparison['change_kind'] not in ('prompt', 'tool', 'workflow')):
            row['reason'] = 'invalid_comparison'
            continue
        try:
            plan = json.loads(evidence_reader.read(comparison.get('plan_ref'), comparison.get('plan_sha256')))
            for name in ARTIFACTS:
                if name != 'plan':
                    evidence_reader.read(comparison.get(name + '_ref'), comparison.get(name + '_sha256'))
        except (OSError, ValueError, TypeError, UnicodeError):
            row['reason'] = 'comparison_artifact_failed'
            continue
        if (not isinstance(plan, dict) or plan.get('kind') != 'improvement_plan'
                or any(plan.get(key) != comparison[key] for key in required)
                or not isinstance(plan.get('task_ids'), list)
                or not all(_nonempty(tid) for tid in plan['task_ids'])
                or type(plan.get('planned_trials_per_task')) is not int
                or plan['planned_trials_per_task'] < 3
                or _timestamp(plan.get('registered_at')) is None
                or not isinstance(plan.get('grader_versions'), dict)
                or not _nonempty(plan.get('task_specs_sha256'))):
            row['reason'] = 'invalid_frozen_plan'
            continue
        cohorts = {}
        duplicate = False
        for task in tasks:
            if (not isinstance(task, dict) or any(task.get(k) != comparison[k] for k in FIELDS)
                    or task_effort(task) != task_effort(comparison)):
                continue
            version = task.get('harness_version')
            if version not in (comparison['baseline_harness_version'], comparison['candidate_harness_version']):
                continue
            if not _nonempty(task.get('task_id')):
                duplicate = True
                continue
            key = version, task['task_id']
            if key in cohorts:
                duplicate = True
            cohorts[key] = task
        baseline = {tid: task for (version, tid), task in cohorts.items()
                    if version == comparison['baseline_harness_version']}
        candidate = {tid: task for (version, tid), task in cohorts.items()
                     if version == comparison['candidate_harness_version']}
        if (duplicate or not baseline or set(baseline) != set(candidate)
                or not all(_nonempty(tid) for tid in baseline)
                or len(plan['task_ids']) != len(baseline)
                or set(plan['task_ids']) != set(baseline)):
            row['reason'] = 'task_set_mismatch'
            continue
        if plan['task_specs_sha256'] != _spec_digest(baseline.values()):
            row['reason'] = 'invalid_frozen_plan'
            continue
        before, after = [], []
        seen_artifacts, seen_traces = set(), set()
        for tid in sorted(baseline):
            left, right = baseline[tid], candidate[tid]
            comparable = (left.get('planned_trials') == plan['planned_trials_per_task']
                          and all(left.get(field) == right.get(field) for field in
                             ('acceptance_criteria', 'reference_solution_ref', 'required_graders', 'planned_trials'))
                          )
            if not comparable:
                break
            a, b = _cohort(left, evidence_reader, since, until), _cohort(right, evidence_reader, since, until)
            if a is None or b is None or a['grader_versions'] != b['grader_versions']:
                break
            if any(_timestamp(t['timestamp']) < _timestamp(plan['registered_at'])
                   for task in (left, right) for t in task['trials']):
                break
            if plan['grader_versions'].get(tid) != dict(a['grader_versions']):
                break
            if (a['artifacts'] & b['artifacts'] or a['traces'] & b['traces']
                    or (a['artifacts'] | b['artifacts']) & seen_artifacts
                    or (a['traces'] | b['traces']) & seen_traces):
                break
            seen_artifacts.update(a['artifacts']); seen_artifacts.update(b['artifacts'])
            seen_traces.update(a['traces']); seen_traces.update(b['traces'])
            before.append(a); after.append(b)
        if len(before) != len(baseline):
            row['reason'] = 'incomplete_or_incomparable_trials'
            continue
        row['tasks'] = len(before)
        row['trials_per_variant'] = sum(item['trials'] for item in before)
        for prefix, values in (('baseline', before), ('candidate', after)):
            row[prefix + '_success'] = sum(item['success'] for item in values) / len(values)
            row[prefix + '_autonomous'] = sum(item['autonomous'] for item in values) / len(values)
        row['success_delta'] = row['candidate_success'] - row['baseline_success']
        row['autonomous_delta'] = row['candidate_autonomous'] - row['baseline_autonomous']
        diffs = [b['autonomous'] - a['autonomous'] for a, b in zip(before, after)]
        row['improved_tasks'] = sum(d > 0 for d in diffs)
        row['regressed_tasks'] = sum(d < 0 for d in diffs)
        row['unchanged_tasks'] = sum(d == 0 for d in diffs)
        row['sign_test_p'] = _sign_pvalue(row['improved_tasks'], row['regressed_tasks'])
        any_quality_regression = any(b['success'] < a['success'] for a, b in zip(before, after))
        if row['autonomous_delta'] <= 0:
            row['status'] = 'no_observed_gain'
        elif any_quality_regression or row['regressed_tasks']:
            row['status'] = 'gain_with_regressions'
        elif row['sign_test_p'] is not None and row['sign_test_p'] <= .05:
            row['status'] = 'supported_gain'
        else:
            row['status'] = 'observed_gain'
    status = ('evaluated' if any(row['reason'] is None for row in rows)
              else 'insufficient_evidence' if rows else 'invalid_input' if diagnostics else 'no_comparisons')
    return {'status': status, 'comparisons': rows,
            'diagnostics': diagnostics, 'evidence_basis': 'local_checked' if evidence_reader else 'none',
            'independent_execution_verified': False,
            'limitations': [
                'Local hash, grading, and pairing checks cannot establish holdout secrecy, independent runs, agent authorship, or freedom from selective reporting.',
                'An independent evaluator must freeze tasks and graders in advance, run both versions in isolation, and retain the raw evidence.',
                'Controlled comparisons require at least three runs per task per version and full session exports. These are this project’s minimum evidence requirements.',
                'supported_gain means locally checked evidence is complete, no task regressed, and the one-sided task-level sign test has p≤0.05. It is not causal proof or certification.',
            ]}


def render_summary(report, markdown=False):
    heading = '## ' if markdown else ''
    lines = [heading + 'Local self-improvement comparison', '']
    if not report['comparisons']:
        lines.append('No predefined controlled before/after comparison is available. L6 self-reports do not prove improvement.')
    for row in report['comparisons']:
        lines.append(f"{row['label']} ({row['source']}): {row['status']}")
        if row['reason']:
            lines.append('Evidence gap: ' + row['reason'])
        else:
            lines.append(f"Tasks {row['tasks']} · Trials per version {row['trials_per_variant']} · "
                         f"Autonomous success rate {row['baseline_autonomous']:.1%} → {row['candidate_autonomous']:.1%} "
                         f"({row['autonomous_delta']:+.1%})")
            lines.append(f"Overall success rate {row['baseline_success']:.1%} → {row['candidate_success']:.1%}; "
                         f"Improved / regressed / unchanged tasks {row['improved_tasks']}/{row['regressed_tasks']}/{row['unchanged_tasks']}; "
                         f"Sign test p={row['sign_test_p'] if row['sign_test_p'] is not None else 'N/A'}")
    lines.append('Local checks are not independent execution. An outside evaluator must control the task suite, runs, and evidence.')
    return '\n'.join(lines)
