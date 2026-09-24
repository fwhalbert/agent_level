"""Show an auto-eval notice when a session starts in an enabled workspace."""

import json
import sys
from pathlib import Path


INSTRUCTION_START = '<!-- agent-level:task-evidence:start -->'
INSTRUCTION_END = '<!-- agent-level:task-evidence:end -->'
NOTICE = 'Auto eval enabled.'
MAX_IMPORT_DEPTH = 8
MAX_INSTRUCTION_BYTES = 1024 * 1024


def has_instructions(path, seen, depth=0):
    if depth > MAX_IMPORT_DEPTH or len(seen) >= 64:
        return False
    try:
        path = path.expanduser().resolve(strict=True)
        if path in seen or not path.is_file() or path.stat().st_size > MAX_INSTRUCTION_BYTES:
            return False
        seen.add(path)
        content = path.read_text(encoding='utf-8')
    except (OSError, RuntimeError, ValueError, UnicodeError):
        return False
    if INSTRUCTION_START in content and INSTRUCTION_END in content:
        return True
    fence = None
    for line in content.splitlines():
        line = line.strip()
        if line.startswith(('```', '~~~')):
            if fence is None:
                fence = line[:3]
            elif line.startswith(fence):
                fence = None
            continue
        if fence is not None or not line.startswith('@'):
            continue
        reference = line[1:].strip()
        if len(reference) >= 2 and reference[0] == reference[-1] and reference[0] in ('"', "'"):
            reference = reference[1:-1]
        imported = Path(reference).expanduser()
        if imported.suffix.lower() != '.md':
            continue
        if not imported.is_absolute():
            imported = path.parent / imported
        if has_instructions(imported, seen, depth + 1):
            return True
    return False


def enabled(directory):
    seen = set()
    for ancestor in (directory, *directory.parents):
        for name in ('AGENTS.md', 'CLAUDE.md'):
            if has_instructions(ancestor / name, seen):
                return True
    return False


def main():
    try:
        event = json.load(sys.stdin)
    except (ValueError, UnicodeError):
        return 0
    if not isinstance(event, dict) or event.get('source') != 'startup':
        return 0
    try:
        directory = Path(event.get('cwd', '')).resolve(strict=True)
    except (OSError, TypeError, ValueError):
        return 0
    if not directory.is_dir() or not enabled(directory):
        return 0
    print(json.dumps({'systemMessage': NOTICE,
                      'hookSpecificOutput': {'hookEventName': 'SessionStart',
                                             'additionalContext': NOTICE}}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
