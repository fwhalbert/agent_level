"""Record daily task acceptance evidence separately from the read-only evaluator."""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4

from assessment.evidence import (MAX_EVIDENCE_BYTES, EvidenceReader, registration_definition,
                                 valid_human_review)
from assessment.collection import RECORD_DIRECTORY


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(directory, name, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    if len(raw) > MAX_EVIDENCE_BYTES:
        raise ValueError('record exceeds evidence size limit')
    temporary = directory / ('.' + name + '.' + uuid4().hex)
    try:
        with temporary.open('xb') as stream:
            stream.write(raw)
        temporary.replace(directory / name)
    finally:
        temporary.unlink(missing_ok=True)
    return {'evidence_ref': name, 'evidence_sha256': hashlib.sha256(raw).hexdigest()}


def start(args):
    repo = args.repo.expanduser().resolve(strict=True)
    workspace = (args.workspace or repo).expanduser().resolve(strict=True)
    if not repo.is_dir() or not workspace.is_dir() or not repo.is_relative_to(workspace):
        raise ValueError('workspace must be the repo or an ancestor directory')
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError('timeout must be positive and finite')
    if any(not value.strip() for value in (args.model, args.reasoning_effort,
                                           args.harness_version, args.criteria)):
        raise ValueError('model, reasoning effort, harness version and criteria must not be empty')
    standard = dict(version=args.criteria_version, author=args.criteria_author,
                    review_source=args.criteria_review_source,
                    reviewer=args.criteria_reviewer, review_ref=args.criteria_review_ref)
    if any(not value.strip() for value in standard.values()):
        raise ValueError('acceptance standard metadata must not be empty; use unknown when unavailable')
    if standard['review_source'] in ('human', 'independent_model') and standard['reviewer'] == 'unknown':
        raise ValueError('a declared human or independent model review requires a reviewer identity')
    command = args.check[1:] if args.check[:1] == ['--'] else args.check
    if any(not item.strip() for item in args.session_id):
        raise ValueError('session IDs must not be empty')
    store = workspace
    for part in ('.' + args.source, RECORD_DIRECTORY, 'tasks'):
        store = store / part
        if store.is_symlink():
            raise ValueError('record directories must not be symlinks')
        store.mkdir(mode=0o700, exist_ok=True)
    task_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid4().hex[:12]
    directory = store / task_id
    directory.mkdir(mode=0o700)
    task = dict(task_id=task_id, repo=str(repo), source=args.source, model=args.model,
                reasoning_effort=args.reasoning_effort,
                harness_version=args.harness_version, suite_id='daily', suite_version='1',
                evaluation_mode='daily', acceptance_criteria=args.criteria,
                acceptance_standard=standard,
                required_graders=['acceptance'], planned_trials=1,
                check_command=command, check_timeout_seconds=args.timeout,
                trials=[dict(trial_id=task_id + '-1', timestamp=now(), status='running',
                             artifact_id=task_id, transcript_kind='collector_journal', graders=[],
                             session_ids=list(dict.fromkeys(args.session_id)))])
    frozen = dict(kind='acceptance_registration', frozen_at=now(), definition=registration_definition(task))
    task['acceptance_registration'] = write_json(directory, 'registration.json', frozen)
    task['trials'][0]['acceptance_registration'] = dict(task['acceptance_registration'])
    write_json(directory, 'results.json', dict(schema_version='1.1', collector='daily-v1', tasks=[task]))
    print(directory)
    return 0


class OutputLimitExceeded(Exception):
    pass


class AcceptanceLaunchFailed(Exception):
    pass


def run_check(command, cwd, timeout, output):
    """Capture bounded output while enforcing a deadline on the process group."""
    try:
        process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as exc:
        raise AcceptanceLaunchFailed(str(exc)) from exc
    deadline = time.monotonic() + timeout
    completed = False
    try:
        with process.stdout, selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            written = 0
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    available = MAX_EVIDENCE_BYTES - written
                    output.write(chunk[:available])
                    written += min(len(chunk), available)
                    if len(chunk) > available:
                        raise OutputLimitExceeded()
            code = process.wait(timeout=max(0, deadline - time.monotonic()))
            completed = True
            return code, False, None
    except subprocess.TimeoutExpired:
        return None, True, 'acceptance timed out'
    except KeyboardInterrupt:
        return None, False, 'acceptance interrupted'
    except OutputLimitExceeded:
        return None, False, 'acceptance output exceeds evidence size limit'
    finally:
        if not completed:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def finish(args):
    directory = args.task_dir.expanduser().absolute()
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError('record directories must not be symlinks')
    with (directory / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = directory / 'results.json'
        if path.is_symlink() or path.stat().st_size > MAX_EVIDENCE_BYTES:
            raise ValueError('invalid task record')
        ledger = json.loads(path.read_text())
        if ledger.get('collector') != 'daily-v1' or len(ledger.get('tasks', [])) != 1:
            raise ValueError('expected a daily-v1 single-task record')
        task = ledger['tasks'][0]
        trial = task['trials'][0]
        if trial['status'] != 'running' and not (args.unknown and trial['status'] == 'grading'):
            raise ValueError('task already finalized or grading; use a new task for another acceptance run')
        frozen_ok, _ = EvidenceReader(directory).verify_registration(task)
        if (not frozen_ok or (task.get('acceptance_registration') is not None
                and trial.get('acceptance_registration') != task['acceptance_registration'])):
            raise ValueError('registered acceptance definition was modified or its evidence is unavailable')
        command = task['check_command']
        if not command and not args.unknown:
            raise ValueError('no acceptance command registered; finish with --unknown REASON')
        if args.unknown is not None and not args.unknown.strip():
            raise ValueError('unknown reason must not be empty')
        journal = dict(kind='collector_journal', task_id=task['task_id'],
                       acceptance_criteria=task['acceptance_criteria'], started_at=trial['timestamp'],
                       command=command, cwd=task['repo'])
        if task.get('acceptance_registration'):
            journal['registration_sha256'] = task['acceptance_registration']['evidence_sha256']
        exit_code, timed_out, error = None, False, args.unknown
        reason = (args.reason or ('interruption' if trial['status'] == 'grading'
                                  else 'verification_unavailable')) if args.unknown else None
        started = time.monotonic()
        if args.unknown:
            trial['status'] = 'interrupted'
        else:
            trial['status'] = 'grading'
            write_json(directory, 'results.json', ledger)
            try:
                with (directory / 'check.log').open('xb') as output:
                    exit_code, timed_out, error = run_check(
                        command, task['repo'], task['check_timeout_seconds'], output)
                output_path = directory / 'check.log'
                if output_path.stat().st_size > MAX_EVIDENCE_BYTES:
                    error = 'acceptance output exceeds evidence size limit'
                else:
                    journal['output_ref'] = 'check.log'
                    journal['output_sha256'] = hashlib.sha256(output_path.read_bytes()).hexdigest()
            except AcceptanceLaunchFailed as exc:
                error = str(exc)
                reason = 'launch_failure'
            except OSError as exc:
                error = str(exc)
                reason = 'evidence_missing'
            if exit_code is not None and exit_code < 0:
                error = 'acceptance terminated by signal'
                reason = 'interruption'
            if error and reason is None:
                reason = ('timeout' if timed_out else
                          'interruption' if error == 'acceptance interrupted' else
                          'output_limit' if error == 'acceptance output exceeds evidence size limit' else
                          'evidence_missing')
            trial['status'] = 'error' if error else 'completed'
        journal.update(finished_at=now(), exit_code=exit_code, timed_out=timed_out, error=error,
                       failure_reason=reason)
        if reason:
            trial['failure_reason'] = reason
        trace = write_json(directory, 'journal.json', journal)
        trial.update(transcript_ref=trace['evidence_ref'], transcript_sha256=trace['evidence_sha256'],
                     duration_seconds=time.monotonic() - started)
        if not error:
            passed = exit_code == 0
            if not passed:
                trial['failure_reason'] = 'acceptance_failed'
            evidence = write_json(directory, 'grader.json', dict(
                kind='command_result', grader_id='acceptance', grader_version='1',
                artifact_id=trial['artifact_id'], exit_code=exit_code, timed_out=False, passed=passed))
            grader = dict(grader_id='acceptance', version='1', type='code', passed=passed, **evidence)
            trial['graders'] = [grader]
            outcome = write_json(directory, 'outcome.json', dict(
                kind='task_outcome', artifact_id=trial['artifact_id'], passed=passed,
                graders=[dict(grader_id='acceptance', sha256=evidence['evidence_sha256'])]))
            trial['outcome'] = dict(passed=passed, **outcome)
        write_json(directory, 'results.json', ledger)
        print(json.dumps(dict(task_dir=str(directory), status=trial['status'],
                              passed=trial.get('outcome', {}).get('passed'), error=error), ensure_ascii=False))
        return 2 if error else (0 if passed else 1)


def review(args):
    """Append declared human review without altering acceptance artifacts or verdicts."""
    directory = args.task_dir.expanduser().absolute()
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError('record directories must not be symlinks')
    review_path = args.review_file.expanduser()
    with review_path.open('rb') as stream:
        raw = stream.read(MAX_EVIDENCE_BYTES + 1)
    if len(raw) > MAX_EVIDENCE_BYTES:
        raise ValueError('review exceeds evidence size limit')
    record = json.loads(raw)
    allowed = {'type', 'reviewer', 'reviewed_at', 'result', 'selection', 'failure_category',
               'human_interventions', 'interventions'}
    if not valid_human_review(record) or set(record) - allowed:
        raise ValueError('invalid typed human review; see the documented review JSON fields')
    with (directory / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = directory / 'results.json'
        if path.is_symlink() or path.stat().st_size > MAX_EVIDENCE_BYTES:
            raise ValueError('invalid task record')
        ledger = json.loads(path.read_text())
        if ledger.get('collector') != 'daily-v1' or len(ledger.get('tasks', [])) != 1:
            raise ValueError('expected a daily-v1 single-task record')
        trial = ledger['tasks'][0]['trials'][0]
        if trial.get('status') in ('running', 'grading'):
            raise ValueError('finish the acceptance attempt before recording retrospective review')
        reference = write_json(directory, 'review-' + uuid4().hex + '.json', record)
        trial.setdefault('human_reviews', []).append(dict(record, **reference))
        write_json(directory, 'results.json', ledger)
    print(json.dumps(dict(task_dir=str(directory), human_review_recorded=True), ensure_ascii=False))
    return 0


def locate(args):
    """Resolve an explicit opaque report reference to a local record directory."""
    from assessment.anthropic import task_reference
    from assessment.collection import load_project_evals
    workspace = args.workspace.expanduser().resolve(strict=True)
    data, reader, _ = load_project_evals(workspace)
    matches = []
    for task in data['tasks'] if data else []:
        if task_reference(task) != args.task_ref:
            continue
        local = reader.task_readers.get(id(task))
        if local is not None:
            matches.append(str(local.root))
    for value in sorted(set(matches)):
        print(value)
    if not matches:
        raise ValueError('no locally discoverable record matches that task reference')
    return 0


def review_plan(args):
    """Select all failed/unknown tasks and a reproducible 20% of successful tasks."""
    import random
    from assessment.anthropic import assess
    from assessment.collection import load_project_evals
    from assessment.logs import Metrics, merge_metrics
    workspace = args.workspace.expanduser().resolve(strict=True)
    data, reader, _ = load_project_evals(workspace)
    report = assess(merge_metrics([Metrics('codex'), Metrics('claude')]), data, evidence_reader=reader)
    mandatory, successful = [], []
    for task in report['task_diagnostics']:
        item = dict(task_ref=task['task_ref'], group_id=task['group_id'])
        if task['task_status'] == 'failure':
            mandatory.append(dict(item, selection='all_failure'))
        elif task['task_status'] == 'unknown':
            mandatory.append(dict(item, selection='all_unknown'))
        else:
            successful.append(item)
    groups = {}
    for item in successful:
        groups.setdefault(item['group_id'], []).append(item)
    rng = random.Random(args.seed)
    sampled, group_counts = [], []
    for group_id, items in sorted(groups.items()):
        items.sort(key=lambda item: item['task_ref'])
        n = math.ceil(len(items) * .2)
        sampled.extend(rng.sample(items, n))
        group_counts.append(dict(group_id=group_id, successful_tasks=len(items), sampled=n))
    selected = mandatory + [dict(item, selection='random_success') for item in sampled]
    print(json.dumps(dict(seed=args.seed, successful_task_fraction=.2, sample_scope='per_group',
                          success_sample_groups=group_counts,
                          selected=sorted(selected, key=lambda item: item['task_ref']),
                          successful_tasks=len(successful), reviewed=False), ensure_ascii=False))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    begin = commands.add_parser('start', help='register criteria and an acceptance command before work')
    begin.add_argument('--repo', type=Path, required=True)
    begin.add_argument('--workspace', type=Path, help='ancestor workspace storing records (default: repo)')
    begin.add_argument('--source', choices=('codex', 'claude'), required=True)
    begin.add_argument('--model', required=True)
    begin.add_argument('--reasoning-effort', '--effort', default='unknown',
                       help='actual effort for this run, or unknown when unavailable')
    begin.add_argument('--harness-version', default='unknown')
    begin.add_argument('--criteria', required=True)
    begin.add_argument('--criteria-version', default='unknown')
    begin.add_argument('--criteria-author', default='unknown')
    begin.add_argument('--criteria-review-source', choices=('human', 'independent_model', 'template', 'self', 'unknown'), default='unknown')
    begin.add_argument('--criteria-reviewer', default='unknown')
    begin.add_argument('--criteria-review-ref', default='unknown')
    begin.add_argument('--session-id', action='append', default=[], help='explicit associated session ID; repeat for multi-session work')
    begin.add_argument('--timeout', type=float, default=300)
    begin.add_argument('check', nargs=argparse.REMAINDER, help='acceptance argv after --; no implicit shell')
    end = commands.add_parser('finish', help='execute the registered acceptance command and save evidence')
    end.add_argument('--task-dir', type=Path, required=True)
    end.add_argument('--unknown', metavar='REASON', help='close without grading when verification is unavailable')
    end.add_argument('--reason', choices=('timeout', 'interruption', 'launch_failure', 'output_limit',
                                         'evidence_missing', 'verification_unavailable'),
                     help='reason used with --unknown (default: interruption for grading, otherwise verification_unavailable)')
    audit = commands.add_parser('review', help='append a declared human review without changing the acceptance verdict')
    audit.add_argument('--task-dir', type=Path, required=True)
    audit.add_argument('--review-file', type=Path, required=True)
    lookup = commands.add_parser('locate', help='read-only lookup of an opaque task reference in local records')
    lookup.add_argument('--workspace', type=Path, required=True)
    lookup.add_argument('--task-ref', required=True)
    plan = commands.add_parser('review-plan', help='read-only seeded sample: all failed/unknown tasks plus 20% successful tasks')
    plan.add_argument('--workspace', type=Path, required=True)
    plan.add_argument('--seed', type=int, required=True, help='explicit reproducible sampling seed')
    args = parser.parse_args(argv)
    try:
        return {'start': start, 'finish': finish, 'review': review, 'locate': locate,
                'review-plan': review_plan}[args.action](args)
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, RecursionError) as exc:
        print(f'[error] {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
