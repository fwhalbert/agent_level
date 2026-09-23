"""Record daily task acceptance evidence separately from the read-only evaluator."""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4

from assessment.evidence import MAX_EVIDENCE_BYTES


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
    if any(not value.strip() for value in (args.model, args.harness_version, args.criteria)):
        raise ValueError('model, harness version and criteria must not be empty')
    command = args.check[1:] if args.check[:1] == ['--'] else args.check
    store = workspace
    for part in ('.' + args.source, 'agent-eval', 'tasks'):
        store = store / part
        if store.is_symlink():
            raise ValueError('record directories must not be symlinks')
        store.mkdir(mode=0o700, exist_ok=True)
    task_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid4().hex[:12]
    directory = store / task_id
    directory.mkdir(mode=0o700)
    task = dict(task_id=task_id, repo=str(repo), source=args.source, model=args.model,
                harness_version=args.harness_version, suite_id='daily', suite_version='1',
                evaluation_mode='daily', acceptance_criteria=args.criteria,
                required_graders=['acceptance'], planned_trials=1,
                check_command=command, check_timeout_seconds=args.timeout,
                trials=[dict(trial_id=task_id + '-1', timestamp=now(), status='running',
                             artifact_id=task_id, transcript_kind='collector_journal', graders=[])])
    write_json(directory, 'results.json', dict(schema_version='1.1', collector='daily-v1', tasks=[task]))
    print(directory)
    return 0


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
        command = task['check_command']
        if not command and not args.unknown:
            raise ValueError('no acceptance command registered; finish with --unknown REASON')
        if args.unknown is not None and not args.unknown.strip():
            raise ValueError('unknown reason must not be empty')
        journal = dict(kind='collector_journal', task_id=task['task_id'],
                       acceptance_criteria=task['acceptance_criteria'], started_at=trial['timestamp'],
                       command=command, cwd=task['repo'])
        exit_code, timed_out, error = None, False, args.unknown
        started = time.monotonic()
        if args.unknown:
            trial['status'] = 'interrupted'
        else:
            trial['status'] = 'grading'
            write_json(directory, 'results.json', ledger)
            try:
                with (directory / 'check.log').open('xb') as output:
                    process = subprocess.Popen(command, cwd=task['repo'], stdout=output,
                                               stderr=subprocess.STDOUT, start_new_session=True)
                    try:
                        exit_code = process.wait(timeout=task['check_timeout_seconds'])
                    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                        timed_out = isinstance(exc, subprocess.TimeoutExpired)
                        error = 'acceptance timed out' if timed_out else 'acceptance interrupted'
                output_path = directory / 'check.log'
                if output_path.stat().st_size > MAX_EVIDENCE_BYTES:
                    error = 'acceptance output exceeds evidence size limit'
                else:
                    journal['output_ref'] = 'check.log'
                    journal['output_sha256'] = hashlib.sha256(output_path.read_bytes()).hexdigest()
            except OSError as exc:
                error = str(exc)
            if exit_code is not None and exit_code < 0:
                error = 'acceptance terminated by signal'
            trial['status'] = 'error' if error else 'completed'
        journal.update(finished_at=now(), exit_code=exit_code, timed_out=timed_out, error=error)
        trace = write_json(directory, 'journal.json', journal)
        trial.update(transcript_ref=trace['evidence_ref'], transcript_sha256=trace['evidence_sha256'],
                     duration_seconds=time.monotonic() - started)
        if not error:
            passed = exit_code == 0
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    begin = commands.add_parser('start', help='register criteria and an acceptance command before work')
    begin.add_argument('--repo', type=Path, required=True)
    begin.add_argument('--workspace', type=Path, help='ancestor workspace storing records (default: repo)')
    begin.add_argument('--source', choices=('codex', 'claude'), required=True)
    begin.add_argument('--model', required=True)
    begin.add_argument('--harness-version', default='unknown')
    begin.add_argument('--criteria', required=True)
    begin.add_argument('--timeout', type=float, default=300)
    begin.add_argument('check', nargs=argparse.REMAINDER, help='acceptance argv after --; no implicit shell')
    end = commands.add_parser('finish', help='execute the registered acceptance command and save evidence')
    end.add_argument('--task-dir', type=Path, required=True)
    end.add_argument('--unknown', metavar='REASON', help='close without grading when verification is unavailable')
    args = parser.parse_args(argv)
    try:
        return start(args) if args.action == 'start' else finish(args)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        print(f'[error] {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
