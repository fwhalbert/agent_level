"""Read project-local daily records and verify each record's own evidence root."""
from collections import Counter
import json
from pathlib import Path

from .evidence import EvidenceCache, EvidenceReader, MAX_EVIDENCE_BYTES
from .history import project_matches

RECORD_DIRECTORY = 'agent_level'

DISCOVERY_NOTE = ('Task record discovery is partial. Identifiable rejected tasks remain unknown; '
                  'unreadable or unassigned records cannot be included in task denominators.')


class ProjectEvidenceReader:
    def __init__(self):
        self.readers = {}
        self.task_readers = {}
        self.cache = EvidenceCache()

    def verify_trial(self, trial):
        reader = self.readers.get(id(trial))
        if reader is None:
            return False, 'evidence_verification_failed'
        return reader.verify_trial(trial)

    def verify_registration(self, task):
        reader = self.task_readers.get(id(task))
        if reader is None:
            return False, 'evidence_verification_failed'
        return reader.verify_registration(task)

    def verify_human_review(self, trial, review):
        reader = self.readers.get(id(trial))
        return reader.verify_human_review(review) if reader is not None else False

    def diagnose_incomplete(self, trial):
        reader = self.readers.get(id(trial))
        return reader.diagnose_incomplete(trial) if reader is not None else 'evidence_missing'


def load_project_evals(project_dir):
    project = Path(project_dir).resolve()
    data = {'schema_version': '1.1', 'tasks': []}
    reader = ProjectEvidenceReader()
    files = 0
    diagnostics = Counter()
    unknown_records = 0
    stores = (parent / agent_dir / RECORD_DIRECTORY / 'tasks'
              for parent in (project,) + tuple(project.parents)
              for agent_dir in ('.codex', '.claude'))
    for store in stores:
        if any(path.is_symlink() for path in (store, store.parent, store.parent.parent)):
            diagnostics['invalid_task_stores'] += 1
            continue
        if not store.is_dir():
            continue
        for path in sorted(store.glob('*/results.json')):
            reason = None
            try:
                if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
                    reason = 'invalid_task_records'
                elif path.stat().st_size > MAX_EVIDENCE_BYTES:
                    reason = 'oversized_task_records'
                else:
                    ledger = json.loads(path.read_text(encoding='utf-8'))
            except OSError:
                reason = 'unreadable_task_records'
            except (ValueError, UnicodeError, RecursionError):
                reason = 'invalid_task_records'
            if reason is not None:
                diagnostics[reason] += 1
                unknown_records += 1
                continue
            tasks = ledger.get('tasks') if isinstance(ledger, dict) else None
            tasks = tasks if isinstance(tasks, list) else []
            identifiable = [task for task in tasks if isinstance(task, dict)
                            and isinstance(task.get('repo'), str) and Path(task['repo']).is_absolute()]
            relevant = [task for task in identifiable if project_matches(task['repo'], project)]
            # Other projects' readable records cannot invalidate the selected project.
            if tasks and len(identifiable) == len(tasks) and not relevant:
                continue
            valid = (isinstance(ledger, dict) and ledger.get('schema_version') in ('1.0', '1.1')
                     and ledger.get('collector') == 'daily-v1' and len(tasks) == 1
                     and len(relevant) == 1 and relevant[0].get('evaluation_mode') == 'daily')
            if not valid:
                diagnostics['invalid_task_records'] += 1
                unknown_records += 1
                # Preserve attributable tasks without giving their trials a trusted reader.
                if not relevant:
                    continue
            local = EvidenceReader(path.parent, cache=reader.cache) if valid else None
            for task in relevant:
                trials = task.get('trials')
                if local is not None:
                    reader.task_readers[id(task)] = local
                if local is not None and isinstance(trials, list):
                    for trial in trials:
                        if isinstance(trial, dict):
                            reader.readers[id(trial)] = local
                data['tasks'].append(task)
            files += 1
    counts = {'files': files, 'tasks': len(data['tasks'])}
    if diagnostics:
        counts.update(unknown_records=unknown_records, diagnostics=dict(diagnostics))
    return (data if files else None), (reader if files else None), counts
