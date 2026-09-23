"""Show an auto-eval notice when a session starts in an enabled workspace."""

import json
import sys
from pathlib import Path


INSTRUCTIONS = 'AUTO_EVALUATION.md'
NOTICE = 'Auto eval enabled.'


def enabled(directory):
    for ancestor in (directory, *directory.parents):
        for name in ('AGENTS.md', 'CLAUDE.md'):
            path = ancestor / name
            try:
                if INSTRUCTIONS in path.read_text(encoding='utf-8'):
                    return True
            except (OSError, UnicodeError):
                continue
    return False


def main():
    try:
        event = json.load(sys.stdin)
    except (ValueError, UnicodeError):
        return 0
    if event.get('source') != 'startup':
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
