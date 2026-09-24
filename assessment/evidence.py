"""Read-only verification of explicitly selected local evidence; no code execution."""
import hashlib
import json
import os
import stat
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_EVIDENCE_BYTES = 16 * 1024 * 1024


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
    suites = [s for s in root.iter('testsuite') if not list(s.iter('testcase')) and not s.findall('testsuite')]
    total = failed = skipped = 0
    for s in suites:
        values = [int(s.get(k, '0')) for k in ('tests', 'failures', 'errors', 'skipped')]
        n, f, e, sk = values
        if min(values) < 0 or f + e + sk > n:
            raise ValueError('invalid_junit_counts')
        total += n; failed += f + e; skipped += sk
    return failed == 0 if total > skipped else None


class EvidenceReader:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError('evidence root must be a directory')
        self.cache = {}

    def read(self, ref, digest):
        if not isinstance(ref, str) or not ref or not isinstance(digest, str) or len(digest) != 64:
            raise ValueError('missing_digest_or_reference')
        path = Path(ref)
        if path.is_absolute() or '..' in path.parts or ':' in ref:
            raise ValueError('unsafe_reference')
        key = ref, digest
        if key in self.cache:
            return self.cache[key]
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
                raw = stream.read(MAX_EVIDENCE_BYTES + 1)
        finally:
            os.close(fd)
        if len(raw) > MAX_EVIDENCE_BYTES or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('evidence_hash_mismatch')
        self.cache[key] = raw
        return raw

    def verify_trial(self, trial):
        """Check hashes, command/JUnit verdicts and artifact association."""
        try:
            transcript = self.read(trial.get('transcript_ref'), trial.get('transcript_sha256'))
            artifact = trial.get('artifact_id')
            if not isinstance(artifact, str) or not artifact:
                raise ValueError('missing_artifact_identity')
            journal = None
            if trial.get('transcript_kind') == 'collector_journal':
                journal = json.loads(transcript)
                if (not isinstance(journal, dict) or journal.get('kind') != 'collector_journal'
                        or journal.get('task_id') != artifact
                        or type(journal.get('exit_code')) is not int or journal['exit_code'] < 0
                        or journal.get('timed_out') is not False or journal.get('error') is not None):
                    raise ValueError('invalid_collector_journal')
                self.read(journal.get('output_ref'), journal.get('output_sha256'))
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
        except (OSError, ValueError, TypeError, KeyError, AttributeError, ET.ParseError):
            # Report fixed labels only; never leak paths, command output or XML.
            return False, 'evidence_verification_failed'
