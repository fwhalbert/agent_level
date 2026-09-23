"""Read project-local daily records and verify each record's own evidence root."""
from pathlib import Path

from .anthropic import load_evals
from .evidence import EvidenceReader, MAX_EVIDENCE_BYTES
from .history import project_matches


class ProjectEvidenceReader:
    def __init__(self):
        self.readers = {}

    def verify_trial(self, trial):
        reader = self.readers.get(id(trial))
        if reader is None:
            return False, 'evidence_verification_failed'
        return reader.verify_trial(trial)


def load_project_evals(project_dir):
    project = Path(project_dir).resolve()
    data = {'schema_version': '1.1', 'tasks': []}
    reader = ProjectEvidenceReader()
    files = 0
    stores = (parent / agent_dir / 'agent-eval' / 'tasks'
              for parent in (project,) + tuple(project.parents)
              for agent_dir in ('.codex', '.claude'))
    for store in stores:
        if not store.is_dir():
            continue
        if any(path.is_symlink() for path in (store, store.parent, store.parent.parent)):
            raise ValueError('自动采集目录不能使用符号链接')
        for path in sorted(store.glob('*/results.json')):
            if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
                raise ValueError('自动采集台账须为普通文件，不能使用符号链接')
            if path.stat().st_size > MAX_EVIDENCE_BYTES:
                raise ValueError('自动采集台账超过 16 MiB')
            ledger = load_evals(path)
            if ledger.get('collector') != 'daily-v1' or len(ledger['tasks']) != 1:
                raise ValueError('自动发现目录中的台账必须是 daily-v1 格式的单任务记录')
            selected = []
            for task in ledger['tasks']:
                if (not isinstance(task, dict) or not isinstance(task.get('repo'), str)
                        or not Path(task['repo']).is_absolute() or task.get('evaluation_mode') != 'daily'):
                    raise ValueError('自动采集台账缺少可辨识的任务 repo')
                if project_matches(task['repo'], project):
                    selected.append(task)
            if not selected:
                continue
            local = EvidenceReader(path.parent)
            for task in selected:
                trials = task.get('trials')
                if isinstance(trials, list):
                    for trial in trials:
                        if isinstance(trial, dict):
                            reader.readers[id(trial)] = local
            data['tasks'].extend(selected)
            files += 1
    return (data if files else None), (reader if files else None), {'files': files, 'tasks': len(data['tasks'])}
