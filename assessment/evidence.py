"""Read-only verification of explicitly selected local evidence; no code execution."""
import hashlib
import json
import os
import stat
import xml.etree.ElementTree as ET
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path

MAX_EVIDENCE_BYTES = 16 * 1024 * 1024
MAX_CACHE_BYTES = 1024 * 1024
MAX_CACHE_ENTRIES = 256

# Frozen acceptance definitions deliberately do not identify a source revision.
REGISTRATION_FIELDS = ('task_id', 'repo', 'source', 'model', 'reasoning_effort',
                       'harness_version', 'suite_id', 'suite_version', 'evaluation_mode',
                       'acceptance_criteria', 'required_graders', 'planned_trials',
                       'check_command', 'check_timeout_seconds', 'acceptance_standard')
REVIEW_RESULTS = ('confirmed', 'overturned', 'inconclusive')
FAILURE_CATEGORIES = ('requirements', 'implementation', 'environment', 'tests',
                      'grader', 'collection', 'unknown')
INTERVENTION_TYPES = ('clarification', 'correction', 'environment', 'approval', 'other')
REVIEW_SELECTIONS = ('all_failure', 'all_unknown', 'random_success', 'targeted')


def registration_definition(task):
    return {field: task.get(field) for field in REGISTRATION_FIELDS}


def valid_human_review(review):
    """Validate declared human metadata; never infer human participation from logs."""
    from datetime import datetime
    if not isinstance(review, dict) or review.get('type') != 'human':
        return False
    if (not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip()
            or review.get('result') not in REVIEW_RESULTS
            or review.get('selection') not in REVIEW_SELECTIONS
            or review.get('failure_category', 'unknown') not in FAILURE_CATEGORIES):
        return False
    try:
        if datetime.fromisoformat(review['reviewed_at'].replace('Z', '+00:00')).tzinfo is None:
            return False
    except (ValueError, TypeError, KeyError, AttributeError):
        return False
    count = review.get('human_interventions')
    if count is not None and (type(count) is not int or count < 0):
        return False
    interventions = review.get('interventions', [])
    if not isinstance(interventions, list):
        return False
    for item in interventions:
        if (not isinstance(item, dict) or item.get('type') not in INTERVENTION_TYPES
                or type(item.get('count')) is not int or item['count'] < 0):
            return False
        minutes = item.get('minutes')
        if minutes is not None:
            import math
            if type(minutes) not in (int, float) or not math.isfinite(minutes) or minutes < 0:
                return False
    if interventions and (count is None or sum(item['count'] for item in interventions) != count):
        return False
    return True


def _aggregate_junit(suite):
    """Reconcile every declared aggregate, including the testsuites root."""
    fields = ('tests', 'failures', 'errors', 'skipped')
    declared = {key: int(suite.attrib[key]) for key in fields if key in suite.attrib}
    if any(value < 0 for value in declared.values()):
        raise ValueError('invalid_junit_counts')
    children = [child for child in suite if child.tag in ('testsuite', 'testsuites')]
    if children:
        results = [_aggregate_junit(child) for child in children]
        counts = tuple(sum(result[index] for result in results) for index in range(4))
        if any(declared[key] != counts[index] for index, key in enumerate(fields)
               if key in declared):
            raise ValueError('inconsistent_junit_aggregates')
    else:
        counts = tuple(declared.get(key, 0) for key in fields)
    n, failures, errors, skipped = counts
    if failures + errors + skipped > n:
        raise ValueError('invalid_junit_counts')
    return counts


def junit_result(raw):
    """Return True/False/None, treating empty/skipped-only reports as unknown."""
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('unsafe_xml')
    root = ET.fromstring(raw)
    if root.tag not in ('testsuite', 'testsuites'):
        raise ValueError('invalid_junit')
    cases = list(root.iter('testcase'))
    if cases:
        reported_failure = False
        for suite in list(root.iter('testsuite')) + ([root] if root.tag == 'testsuites' else []):
            values = {k: int(suite.get(k, '0')) for k in ('tests', 'failures', 'errors', 'skipped')}
            if min(values.values()) < 0:
                raise ValueError('invalid_junit_counts')
            if 'tests' in suite.attrib and values['tests'] != len(list(suite.iter('testcase'))):
                raise ValueError('incomplete_junit_cases')
            if 'skipped' in suite.attrib and values['skipped'] != sum(c.find('skipped') is not None for c in suite.iter('testcase')):
                raise ValueError('inconsistent_junit_skips')
            reported_failure |= bool(values['failures'] or values['errors'])
        if reported_failure:
            return False
        run = [c for c in cases if c.find('skipped') is None]
        return (all(c.find('failure') is None and c.find('error') is None for c in run)
                if run else None)
    total, failures, errors, skipped = _aggregate_junit(root)
    return failures + errors == 0 if total > skipped else None


class EvidenceCache:
    """Byte-bounded LRU cache, shared by all roots in automatic discovery."""
    def __init__(self, max_bytes=MAX_CACHE_BYTES):
        self.max_bytes = max_bytes
        self.byte_size = 0
        self.entries = OrderedDict()

    def get(self, key):
        if key not in self.entries:
            return None
        self.entries.move_to_end(key)
        return self.entries[key]

    def put(self, key, raw):
        if self.max_bytes <= 0 or len(raw) > self.max_bytes:
            return
        previous = self.entries.pop(key, None)
        if previous is not None:
            self.byte_size -= len(previous)
        while self.entries and (self.byte_size + len(raw) > self.max_bytes
                                or len(self.entries) >= MAX_CACHE_ENTRIES):
            _, evicted = self.entries.popitem(last=False)
            self.byte_size -= len(evicted)
        self.entries[key] = raw
        self.byte_size += len(raw)


class EvidenceReader:
    def __init__(self, root, *, cache=None):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError('evidence root must be a directory')
        self.cache = cache if cache is not None else EvidenceCache()

    def _reference(self, ref, digest):
        if not isinstance(ref, str) or not ref or not isinstance(digest, str) or len(digest) != 64:
            raise ValueError('missing_digest_or_reference')
        path = Path(ref)
        if path.is_absolute() or '..' in path.parts or ':' in ref:
            raise ValueError('unsafe_reference')
        return path

    @contextmanager
    def _open(self, path):
        # Traverse with directory FDs and O_NOFOLLOW to reject symlinks/races.
        fd = os.open(str(self.root), os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in path.parts[:-1]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd); fd = next_fd
            file_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(file_fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_EVIDENCE_BYTES:
                    raise ValueError('invalid_evidence_file')
                yield stream
        finally:
            os.close(fd)

    def read(self, ref, digest):
        path = self._reference(ref, digest)
        key = self.root, ref, digest
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        with self._open(path) as stream:
            raw = stream.read(MAX_EVIDENCE_BYTES + 1)
        if len(raw) > MAX_EVIDENCE_BYTES or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('evidence_hash_mismatch')
        self.cache.put(key, raw)
        return raw

    def verify_file(self, ref, digest):
        """Check hash-only artifacts without retaining their output or transcript."""
        path = self._reference(ref, digest)
        hasher, size = hashlib.sha256(), 0
        with self._open(path) as stream:
            while chunk := stream.read(65536):
                size += len(chunk)
                if size > MAX_EVIDENCE_BYTES:
                    raise ValueError('invalid_evidence_file')
                hasher.update(chunk)
        if hasher.hexdigest() != digest:
            raise ValueError('evidence_hash_mismatch')
        return True

    def verify_registration(self, task):
        registration = task.get('acceptance_registration')
        if registration is None:
            try:
                with self._open(Path('registration.json')):
                    pass
            except FileNotFoundError:
                return True, None  # Genuine legacy records have no freeze sidecar.
            except (OSError, ValueError):
                pass
            return False, 'acceptance_registration_invalid'
        try:
            raw = self.read(registration.get('evidence_ref'), registration.get('evidence_sha256'))
            value = json.loads(raw)
            if (not isinstance(value, dict) or value.get('kind') != 'acceptance_registration'
                    or value.get('definition') != registration_definition(task)
                    or not isinstance(value.get('frozen_at'), str)
                    or not isinstance(task.get('trials'), list)
                    or any(not isinstance(trial, dict) or trial.get('acceptance_registration') != registration
                           for trial in task['trials'])):
                raise ValueError('registration_mismatch')
            return True, None
        except (OSError, ValueError, TypeError, AttributeError, RecursionError):
            return False, 'acceptance_registration_invalid'

    def verify_human_review(self, trial_or_review, review=None):
        # Direct explicit imports pass (trial, review); collection adapters already
        # choose the task root and may pass the review alone.
        review = trial_or_review if review is None else review
        try:
            value = json.loads(self.read(review.get('evidence_ref'), review.get('evidence_sha256')))
            expected = {key: val for key, val in review.items()
                        if key not in ('evidence_ref', 'evidence_sha256')}
            return valid_human_review(value) and value == expected
        except (OSError, ValueError, TypeError, AttributeError, RecursionError):
            return False

    def diagnose_incomplete(self, trial):
        """Interpret only hash-checked fixed collector states, never report raw errors."""
        if trial.get('transcript_kind') != 'collector_journal':
            return 'execution_incomplete'
        if not trial.get('transcript_ref') or not trial.get('transcript_sha256'):
            return 'execution_incomplete' if trial.get('status') in ('running', 'grading') else 'evidence_missing'
        try:
            value = json.loads(self.read(trial.get('transcript_ref'), trial.get('transcript_sha256')))
            if not isinstance(value, dict) or value.get('kind') != 'collector_journal':
                return 'evidence_verification_failed'
            if value.get('task_id') != trial.get('artifact_id'):
                return 'evidence_verification_failed'
            reason = value.get('failure_reason')
            if reason in ('timeout', 'interruption', 'launch_failure', 'output_limit',
                          'evidence_missing', 'verification_unavailable'):
                return reason
            if value.get('timed_out') is True:
                return 'timeout'
            if value.get('error') in ('acceptance interrupted', 'acceptance terminated by signal'):
                return 'interruption'
            if value.get('error') == 'acceptance output exceeds evidence size limit':
                return 'output_limit'
            code = value.get('exit_code')
            if type(code) is int and code < 0:
                return 'interruption'
            # Old arbitrary OSError text cannot safely distinguish launch and collection.
            return 'execution_incomplete'
        except FileNotFoundError:
            return 'execution_incomplete' if trial.get('status') in ('running', 'grading') else 'evidence_missing'
        except (OSError, ValueError, TypeError, AttributeError, RecursionError):
            return 'evidence_verification_failed'

    def verify_trial(self, trial):
        """Check hashes, command/JUnit verdicts and artifact association."""
        try:
            transcript_ref, transcript_digest = trial.get('transcript_ref'), trial.get('transcript_sha256')
            artifact = trial.get('artifact_id')
            if not isinstance(artifact, str) or not artifact:
                raise ValueError('missing_artifact_identity')
            journal = None
            if trial.get('transcript_kind') == 'collector_journal':
                journal = json.loads(self.read(transcript_ref, transcript_digest))
                if (not isinstance(journal, dict) or journal.get('kind') != 'collector_journal'
                        or journal.get('task_id') != artifact
                        or type(journal.get('exit_code')) is not int or journal['exit_code'] < 0
                        or journal.get('timed_out') is not False or journal.get('error') is not None):
                    raise ValueError('invalid_collector_journal')
                self.verify_file(journal.get('output_ref'), journal.get('output_sha256'))
                registration = trial.get('acceptance_registration')
                if registration is None and journal.get('registration_sha256') is not None:
                    raise ValueError('missing_journal_registration')
                if registration is not None:
                    frozen = json.loads(self.read(registration.get('evidence_ref'), registration.get('evidence_sha256')))
                    definition = frozen.get('definition', {})
                    if (frozen.get('kind') != 'acceptance_registration'
                            or definition.get('task_id') != artifact
                            or definition.get('check_command') != journal.get('command')
                            or definition.get('acceptance_criteria') != journal.get('acceptance_criteria')
                            or journal.get('registration_sha256') != registration.get('evidence_sha256')):
                        raise ValueError('journal_registration_mismatch')
            else:
                self.verify_file(transcript_ref, transcript_digest)
            for grader in trial.get('graders', []):
                raw = self.read(grader.get('evidence_ref'), grader.get('evidence_sha256'))
                if grader.get('type') != 'code':
                    raise ValueError('grader_not_machine_verifiable')
                result = json.loads(raw)
                if not isinstance(result, dict) or result.get('kind') != 'command_result':
                    raise ValueError('unsupported_grader_evidence')
                code = result.get('exit_code')
                if type(code) is not int or code < 0 or result.get('timed_out') is not False:
                    raise ValueError('command_incomplete')
                if journal is not None and code != journal['exit_code']:
                    raise ValueError('journal_grader_mismatch')
                passed = code == 0
                junit = result.get('junit')
                if junit is not None:
                    verdict = junit_result(self.read(junit.get('ref'), junit.get('sha256')))
                    if verdict is None:
                        raise ValueError('empty_junit')
                    passed = passed and verdict
                if (not isinstance(grader.get('version'), str) or not grader['version'].strip()
                        or grader.get('passed') is not passed or result.get('passed') is not passed
                        or result.get('artifact_id') != artifact
                        or result.get('grader_id') != grader.get('grader_id')
                        or result.get('grader_version') != grader.get('version')):
                    raise ValueError('grader_evidence_mismatch')
            outcome = trial.get('outcome', {})
            result = json.loads(self.read(outcome.get('evidence_ref'), outcome.get('evidence_sha256')))
            if (not isinstance(result, dict) or result.get('kind') != 'task_outcome'
                    or result.get('artifact_id') != artifact
                    or type(result.get('passed')) is not bool or result['passed'] != outcome.get('passed')):
                raise ValueError('outcome_evidence_mismatch')
            expected = [{'grader_id': g['grader_id'], 'sha256': g['evidence_sha256']} for g in trial['graders']]
            if result.get('graders') != expected:
                raise ValueError('outcome_grader_mismatch')
            return True, None
        except FileNotFoundError:
            return False, 'evidence_missing'
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, ET.ParseError):
            # Report fixed labels only; never leak paths, command output or XML.
            return False, 'evidence_verification_failed'
