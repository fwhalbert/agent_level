"""Local log adapters. Raw messages and tool arguments never leave this module."""
from __future__ import annotations

import json
import math
import re
import shlex
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .history import History, project_matches, command_verdict, exit_code

DELEGATION_TOOLS = {"Task", "Agent", "Workflow", "spawn_agent", "send_input", "followup_task"}
WORKFLOW_TOOLS = {"Workflow"}
FORBIDDEN_NAMES = {".credentials.json", "auth.json", ".env", "id_rsa", "id_ed25519"}

# Higher values take priority; assign each command its highest-priority category.
BASH_CATEGORIES = [
    # (name, priority, regex over a sub-command)
    ("ci", 90, r"^(gh\s+(run|workflow)|act\b|circleci\b|buildkite\b)"),
    ("pr", 85, r"^gh\s+pr\b|^glab\s+mr\b|^hub\s+pull-request\b"),
    ("test", 80, r"^(pytest|tox|nose2|jest|vitest|mocha|ctest|gtest\w*)\b"
                 r"|^python[0-9.]*\s+(-m\s+)?(pytest|unittest)\b"
                 r"|^(npm|pnpm|yarn|bun)\s+(run\s+)?test\b"
                 r"|^(cargo|go|dotnet|mvn|gradle|swift)\s+test\b"
                 # make run* is treated as verification for embedded builds.
                 r"|^make\s+(-\S+\s+)*(check|test|run)(-\S+)?\b"
                 # Direct execution of local test binaries or scripts: ./test_x, ./build/bin/foo_test, ./run_tests.sh
                 r"|^(\./|\.\./|/)\S*(^|[/_-])?test[\w.-]*\b"
                 r"|^\./?run_tests?\b"
                 r"|^(\S*/)?[\w.-]*(?<![A-Za-z])(tests?|check)(?![A-Za-z])[\w.-]*\.(sh|py)\b"),
    ("build", 75, r"^(make|cmake|ninja|bazel|meson|gcc|g\+\+|clang|clang\+\+|cc|ld|tsc|webpack|vite|esbuild|rollup)\b"
                  r"|^(cargo|go|dotnet|mvn|gradle|swift)\s+build\b"
                  r"|^(npm|pnpm|yarn|bun)\s+(run\s+)?build\b"
                  r"|^west\s+build\b|^idf\.py\b|^xcodebuild\b"
                  r"|^(\S*/)?[\w.-]*(?<![A-Za-z])build(?![A-Za-z])[\w.-]*\.(sh|py)\b"),
    ("git", 70, r"^git\b|^gh\s+(repo|issue|api|release)\b|^glab\b"),
    ("docker", 65, r"^(docker|docker-compose|podman|kubectl|helm)\b"),
    ("ssh", 60, r"^(ssh|scp|sftp|rsync)\b"),
    ("node", 55, r"^(node|npm|npx|pnpm|yarn|bun|deno)\b"),
    ("python", 50, r"^(python[0-9.]*|pip[0-9.]*|uv|poetry|conda|ipython|jupyter)\b"),
    ("search", 40, r"^(grep|egrep|fgrep|rg|ag|ack|find|fd|locate|which|whereis)\b"),
    ("read", 30, r"^(cat|bat|head|tail|less|more|sed|awk|wc|ls|ll|tree|stat|file|du|df|jq|column|sort|uniq|cut|diff|nl|xxd|od|realpath|basename|dirname|pwd|echo|printf|date)\b"),
]
BASH_CATEGORY_ORDER = ["search", "read", "build", "test", "git", "python",
                       "node", "docker", "ssh", "pr", "ci", "other"]

_COMPILED_BASH = [(name, prio, re.compile(pat)) for name, prio, pat in BASH_CATEGORIES]
VERIFICATION_CATEGORIES = {"build", "test"}
PATH_EXECUTABLES = {
    'bash', 'sh', 'zsh', 'pytest', 'tox', 'nose2', 'jest', 'vitest', 'mocha', 'ctest',
    'npm', 'pnpm', 'yarn', 'bun', 'cargo', 'go', 'dotnet', 'mvn', 'gradle', 'swift',
    'make', 'cmake', 'ninja', 'uv', 'poetry', 'env', 'sudo', 'timeout', 'stdbuf',
}


def _shell_segments(command):
    # Strip heredoc bodies before tokenization, including redirections and <<-.
    lines = command.splitlines(keepends=True)
    kept, pending = [], []
    for line in lines:
        if pending:
            delimiter, tabs = pending[0]
            if (line.lstrip("\t") if tabs else line).rstrip("\r\n") == delimiter:
                pending.pop(0)
            continue
        kept.append(line)
        for match in re.finditer(r"<<(-?)\s*(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z_][\w]*))", line):
            pending.append((next(v for v in match.groups()[1:] if v is not None), bool(match[1])))
    # Split the original characters before shlex removes quotes; otherwise an
    # argument consisting solely of ";" becomes indistinguishable from syntax.
    segment, quote, escaped, comment = [], None, False, False
    for char in "".join(kept):
        if comment:
            if char != "\n":
                continue
            comment = False
        if escaped:
            segment.append(char)
            escaped = False
        elif char == "\\" and quote != "'":
            segment.append(char)
            escaped = True
        elif quote:
            segment.append(char)
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            segment.append(char)
            quote = char
        elif char == "#" and (not segment or segment[-1].isspace()):
            comment = True
        elif char in ";&|()\n":
            tokens = shlex.split("".join(segment))
            if tokens:
                yield tokens
            segment = []
        else:
            segment.append(char)
    tokens = shlex.split("".join(segment))
    if tokens:
        yield tokens


def _unwrap(tokens):
    tokens = list(tokens)
    while tokens:
        first = tokens[0]
        basename = Path(first).name
        if ('/' in first and not re.match(r'^[A-Za-z_][\w]*=', first)
                and (basename in PATH_EXECUTABLES or re.fullmatch(r'python[0-9.]*', basename))):
            first = tokens[0] = basename
        if re.match(r"^[A-Za-z_][\w]*=", first):
            tokens.pop(0)
        elif first in ("sudo", "time", "nohup", "exec", "command", "env", "!", "{"):
            tokens.pop(0)
            while tokens and tokens[0].startswith("-"):
                flag = tokens.pop(0)
                if flag in ("-u", "-g") and tokens:
                    tokens.pop(0)
        elif first == "timeout" and len(tokens) > 2:
            tokens = tokens[2:]
        elif first == "stdbuf" and len(tokens) > 2:
            tokens = tokens[2:]
        elif first in ("uv", "poetry") and tokens[1:2] == ["run"]:
            tokens = tokens[2:]
        elif first in ("bash", "sh", "zsh") and len(tokens) > 2 and re.fullmatch(r"-[a-z]*c[a-z]*", tokens[1]):
            return tokens, tokens[2]
        elif first in ("bash", "sh", "zsh") and len(tokens) > 1 and not tokens[1].startswith("-"):
            tokens.pop(0)
        else:
            break
    return tokens, None


def _recorder_finish(tokens):
    if re.fullmatch(r'python[0-9.]*', tokens[0]):
        tokens = tokens[1:]
        if tokens[:2] == ['-m', 'agent_level_record']:
            tokens = ['agent-level-record', *tokens[2:]]
        elif tokens and Path(tokens[0]).name == 'agent_level_record.py':
            tokens = ['agent-level-record', *tokens[1:]]
    if not tokens:
        return None
    name = Path(tokens[0]).name
    if name == 'agent-level-record':
        args = tokens[1:]
    elif name == 'agent-level' and tokens[1:2] == ['record']:
        args = tokens[2:]
    else:
        return None
    for arg in args[1:]:
        option = arg.split('=', 1)[0]
        if option == '-h' or (option.startswith('--') and len(option) > 2
                             and ('--help'.startswith(option) or '--unknown'.startswith(option))):
            return False
    return args[:1] == ['finish']


def _classify_bash(command, _depth=0):
    if not isinstance(command, str) or not command or _depth > 3:
        return "other", False
    best_name, best_prio, recorder = "other", -1, False
    priorities = dict((name, prio) for name, prio, _ in _COMPILED_BASH)
    try:
        segments = list(_shell_segments(command))
    except ValueError:
        return "other", False
    for tokens in segments:
        tokens, nested = _unwrap(tokens)
        if not tokens or tokens[0] == "cd":
            continue
        if nested is not None:
            name, nested_recorder = _classify_bash(nested, _depth + 1)
            recorder = recorder or nested_recorder
            prio = priorities.get(name, -1)
            if prio > best_prio:
                best_name, best_prio = name, prio
            continue
        finish = _recorder_finish(tokens)
        if finish is not None:
            if finish:
                recorder = True
                if priorities['test'] > best_prio:
                    best_name, best_prio = 'test', priorities['test']
            continue
        # Match only the command and its arguments; separators inside quoted tokens stay data.
        sub = " ".join(tokens)
        for name, prio, rx in _COMPILED_BASH:
            if rx.search(sub):
                if prio > best_prio:
                    best_name, best_prio = name, prio
                break
    return best_name, recorder


def classify_bash(command: str, _depth=0) -> str:
    """Classify literal shell commands, never execute them. Unparsed input is other."""
    return _classify_bash(command, _depth)[0]


# IDE, CLI, and system wrappers are not human inputs.
MACHINE_BLOCK_RE = re.compile(
    r"<ide_opened_file>.*?</ide_opened_file>"
    r"|<ide_selection>.*?</ide_selection>"
    r"|<ide_diagnostics>.*?</ide_diagnostics>"
    r"|<local-command-stdout>.*?</local-command-stdout>"
    r"|<local-command-stderr>.*?</local-command-stderr>"
    r"|<system-reminder>.*?</system-reminder>"
    r"|<command-message>.*?</command-message>"
    r"|<command-args>\s*</command-args>"
    r"|<user-prompt-submit-hook>.*?</user-prompt-submit-hook>",
    re.DOTALL,
)
CAVEAT_RE = re.compile(
    r"Caveat: The messages below were generated by the user while running local commands.*?$",
    re.MULTILINE,
)
OPEN_TAG_RE = re.compile(r"</?[a-zA-Z][\w:-]*>")

HUMAN_FILTER_RULES = [
    "type == user AND message.role == user",
    "drop isSidechain (subagent turns)",
    "drop isMeta",
    "drop tool_result-only messages",
    "drop IDE notifications / local-command stdout / system-reminder wrappers",
    "keep slash-command invocations (<command-name>) as human input",
]


def is_human_input(rec: dict) -> bool:
    """Identify human input from record structure without retaining its text."""
    if rec.get("type") != "user":
        return False
    if rec.get("isSidechain"):
        return False
    if rec.get("isMeta"):
        return False
    msg = rec.get("message")
    if not isinstance(msg, dict) or msg.get("role") != "user":
        return False

    content = msg.get("content")
    text_parts = []
    has_attachment = False
    if isinstance(content, str):
        text_parts.append(content)
    elif isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            btype = b.get("type")
            if btype == "tool_result":
                continue
            if btype in ("image", "document"):
                has_attachment = True
            if btype == "text":
                if isinstance(b.get("text"), str):
                    text_parts.append(b["text"])
    else:
        return False

    raw = "\n".join(text_parts)
    if "<command-name>" in raw:
        return True  # The user explicitly entered a slash command.
    stripped = CAVEAT_RE.sub("", MACHINE_BLOCK_RE.sub("", raw))
    stripped = OPEN_TAG_RE.sub("", stripped).strip()
    return has_attachment or bool(stripped)


def parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def record_ts(rec: dict):
    ts = rec.get("timestamp")
    if not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except ValueError:
        return None


class Metrics:
    def __init__(self, source="claude"):
        self.source = source
        self.sources = {source}
        self.diagnostics = Counter()
        self.history = History()
        self.project_filtered = False
        self.edit_calls = 0
        self.engineering_sessions = set()
        self._edited_sessions = {}
        self.edited_sessions = set()
        self._final_edits = {}
        self._verification_events = {}
        self._event_sequence = 0
        self._orchestrators = set()
        self._expanded_orchestrators = set()
        self.engineering_days = set()
        self.files_scanned = 0
        self.files_with_data = 0
        self.records = 0
        self.assistant = 0
        self.assistant_sidechain = 0
        self.humanish_user = 0
        self.user_records = 0
        self.subagent_files = 0

        self.tools = Counter()
        self.tool_calls = 0
        self.tool_calls_sidechain = 0
        self.bash = Counter()

        self.cache_read = 0
        self.cache_creation = 0
        self.output_tokens = 0
        self.input_tokens = 0
        self.reasoning_output_tokens = 0
        self.model_usage = {}
        self.daily_model_usage = {}
        self.role_usage = {}
        self.daily_role_usage = {}

        self.sessions = set()
        self.first_ts = None
        self.last_ts = None
        self.days = set()
        self.parse_errors = 0

        self.stats_days = 0
        self.stats_messages = 0
        self.stats_sessions = 0
        self.stats_tool_calls = 0
        self.stats_available = False
        self.stats_window = ""

    @property
    def tool_per_human(self):
        return self.tool_calls / self.humanish_user if self.humanish_user else 0.0

    @property
    def assistant_per_human(self):
        return self.assistant / self.humanish_user if self.humanish_user else 0.0

    @property
    def cache_reuse(self):
        return self.cache_read / self.cache_creation if self.cache_creation else None

    @property
    def workflow_calls(self):
        return sum(self.tools[t] for t in WORKFLOW_TOOLS)

    @property
    def delegation_tool_calls(self):
        return sum(self.tools[t] for t in DELEGATION_TOOLS)

    @property
    def bash_total(self):
        return sum(self.bash.values())

    @property
    def verification_calls(self):
        return sum(self.bash[c] for c in VERIFICATION_CATEGORIES)

    @property
    def verification_ratio(self):
        return self.verification_calls / self.bash_total if self.bash_total else 0.0


def _count(value, m):
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        m.diagnostics['invalid_numeric_fields'] += 1
        return 0
    if not math.isfinite(value) or value < 0 or int(value) != value:
        m.diagnostics['invalid_numeric_fields'] += 1
        return 0
    return int(value)


def _paths(root, pattern, m):
    if root.is_symlink():
        m.diagnostics['skipped_symlinks'] += 1
        return
    if not root.is_dir():
        return
    for path in sorted(root.rglob(pattern)):
        # Do not follow transcript symlinks into credentials or arbitrary files.
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root and root in p.parents):
            m.diagnostics['skipped_symlinks'] += 1
            continue
        if path.name not in FORBIDDEN_NAMES and path.is_file():
            yield path


def _records(path, m):
    try:
        with path.open(encoding='utf-8', errors='replace') as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    m.parse_errors += 1
                    continue
                if isinstance(rec, dict):
                    yield rec
                else:
                    m.diagnostics['invalid_records'] += 1
    except OSError:
        m.diagnostics['unreadable_files'] += 1


def _in_window(ts, since, until):
    return not (since or until) or (ts is not None and
            (since is None or ts >= since) and (until is None or ts < until))


def _observe(m, ts, sid):
    m.records += 1
    if ts:
        m.first_ts = min(m.first_ts, ts) if m.first_ts else ts
        m.last_ts = max(m.last_ts, ts) if m.last_ts else ts
        m.days.add(ts.date())
    m.sessions.add(sid)


EDIT_TOOLS = {'Edit', 'Write', 'NotebookEdit', 'apply_patch'}
SHELL_TOOLS = {'Bash', 'exec_command', 'shell', 'shell_command', 'local_shell'}
KNOWN_TOOLS = EDIT_TOOLS | SHELL_TOOLS | DELEGATION_TOOLS | {
    'Read', 'Glob', 'Grep', 'WebFetch', 'WebSearch', 'TodoWrite', 'ToolSearch',
    'exec', 'write_stdin', 'wait', 'wait_agent', 'list_agents', 'send_message',
    'request_user_input', 'request_user_input_async', 'update_plan', 'view_image',
    'web_search_call', 'image_generation_call', 'other_tool',
}


def _tool(m, name, inp, sid, sidechain, ts=None, call_id=None):
    name = name.rsplit('.', 1)[-1] if isinstance(name, str) else 'other_tool'
    name = name if name in KNOWN_TOOLS else 'other_tool'
    m.tools[name] += 1
    m.tool_calls += 1
    m.tool_calls_sidechain += int(sidechain)
    m._event_sequence += 1
    order = (ts, m._event_sequence)
    if name in EDIT_TOOLS:
        m.edit_calls += 1
        m._edited_sessions[sid] = ts
        m.edited_sessions.add(sid)
        previous = m._final_edits.get(sid)
        if previous is None or ts is None or previous[0] is None or order > previous:
            m._final_edits[sid] = order
    if name == 'exec':
        key = (sid, call_id) if isinstance(call_id, str) and call_id else (sid, m._event_sequence)
        m._orchestrators.add(key)
    if name in SHELL_TOOLS:
        cmd = inp.get('command', inp.get('cmd', '')) if isinstance(inp, dict) else ''
        if isinstance(cmd, list) and all(isinstance(v, str) for v in cmd):
            cmd = shlex.join(cmd)
        category, recorder = _classify_bash(cmd)
        m.bash[category] += 1
        if category in VERIFICATION_CATEGORIES:
            key = (sid, call_id) if isinstance(call_id, str) and call_id else (sid, m._event_sequence)
            m._verification_events[key] = (order, category)
            m.history.call(sid, call_id, recorder)
        edited_at = m._edited_sessions.get(sid)
        if category in VERIFICATION_CATEGORIES and edited_at is not None and ts is not None and ts >= edited_at:
            m.engineering_sessions.add(sid)
            m.engineering_days.add(ts.date())
        return category


def verification_coverage(m):
    """Visible edits and verification returns, never a task-acceptance claim.

    The final status uses the latest recognized build/test call after the last
    observed edit in that session. Missing timestamps or returns stay unknown.
    These session counts cannot establish whether a test covered the changed code.
    """
    summary = m.history.summary()
    counts = Counter()
    categories = {name: Counter(attempts=0, passed=0, failed=0, unknown=0)
                  for name in sorted(VERIFICATION_CATEGORIES)}
    events_by_session = {}
    for key, (order, category) in m._verification_events.items():
        events_by_session.setdefault(key[0], []).append((order, key))
        verdict = m.history.results.get(key)
        categories[category]['attempts'] += 1
        categories[category]['passed' if verdict is True else 'failed' if verdict is False else 'unknown'] += 1
    for sid in m.edited_sessions:
        edit = m._final_edits.get(sid)
        events = events_by_session.get(sid, [])
        if not events:
            counts['without_verification'] += 1
            continue
        if edit is None or edit[0] is None or any(order[0] is None for order, _ in events):
            counts['unknown'] += 1
            counts['order_unknown'] += 1
            continue
        after = [(order, key) for order, key in events if order > edit]
        if not after:
            counts['without_verification'] += 1
            continue
        counts['verified'] += 1
        _, latest = max(after)
        verdict = m.history.results.get(latest)
        counts['passed' if verdict is True else 'failed' if verdict is False else 'unknown'] += 1
    denominator = len(m.edited_sessions)
    return {
        'edited_sessions': denominator,
        'any_edit_then_verify_sessions': len(m.engineering_sessions),
        'final_edit_verified_sessions': counts['verified'],
        'final_edit_verification_passed_sessions': counts['passed'],
        'final_edit_verification_failed_sessions': counts['failed'],
        'final_edit_verification_unknown_sessions': counts['unknown'],
        'final_edit_without_verification_sessions': counts['without_verification'],
        'final_edit_order_unknown_sessions': counts['order_unknown'],
        'final_edit_verification_coverage': counts['verified'] / denominator if denominator else None,
        'final_edit_success_coverage': counts['passed'] / denominator if denominator else None,
        'verification_attempts': summary['verification_calls'],
        'verification_passed': summary['verification_passed'],
        'verification_failed': summary['verification_failed'],
        'verification_unknown': summary['verification_unknown'],
        'categories': {name: dict(values) for name, values in categories.items()},
        'note': 'Only visible calls are counted. Final status is the latest recognized build/test '
                'return after the last observed edit; missing ordering or returns remain unknown. '
                'A successful return does not prove requirement coverage or task acceptance.',
    }


def observability(m):
    """Report trace coverage without inferring behavior from opaque JavaScript."""
    total = len(m._orchestrators)
    expanded = len(m._orchestrators & m._expanded_orchestrators)
    opaque = total - expanded
    # Directly constructed metrics and imported older counters remain usable.
    opaque = max(opaque, m.diagnostics['opaque_orchestrator_calls'])
    total = max(total, expanded + opaque)
    unparsed = m.parse_errors + m.diagnostics['unsupported_records'] + m.diagnostics['invalid_records']
    return {
        'status': 'partial' if opaque or unparsed or m.diagnostics['missing_or_invalid_timestamps'] else 'direct',
        'recognized_tool_calls': m.tool_calls,
        'structured_nested_tool_calls': m.diagnostics['structured_nested_tool_calls'],
        'public_jsonl_tool_calls': m.diagnostics['public_jsonl_tool_calls'],
        'orchestrator_calls': total,
        'expanded_orchestrator_calls': expanded,
        'opaque_orchestrator_calls': opaque,
        'orchestrator_expansion_ratio': expanded / total if total else None,
        'unparsed_records': unparsed,
        'missing_timestamp_records': m.diagnostics['missing_or_invalid_timestamps'],
        'may_undercount_edits_and_verification': bool(opaque or unparsed or m.diagnostics['missing_or_invalid_timestamps']),
        'note': 'Expansion requires an explicit complete nested trace. Visible edit sessions are '
                'a lower bound when logs are incomplete. Missing timestamps cannot enter dated '
                'windows or prove final ordering; unobserved calls are not zero calls.',
    }



USAGE_FIELDS = ('input_tokens', 'cache_read', 'cache_creation', 'output_tokens',
                'reasoning_output_tokens')


def _model_name(value):
    return value.strip() if isinstance(value, str) and value.strip() else 'unknown'


def _add_usage(m, usage, model, ts, reasoning_reported=False, role='unknown'):
    """Keep all-time and daily model totals on the same deduplicated stream."""
    for key in USAGE_FIELDS:
        setattr(m, key, getattr(m, key) + usage.get(key, 0))
    counts = Counter({key: usage.get(key, 0) for key in USAGE_FIELDS})
    counts['reasoning_records'] = int(reasoning_reported)
    key = (m.source, _model_name(model))
    m.model_usage.setdefault(key, Counter()).update(counts)
    if ts is not None:
        m.daily_model_usage.setdefault((ts.date().isoformat(),) + key, Counter()).update(counts)
    role_key = (m.source, role)
    m.role_usage.setdefault(role_key, Counter()).update(counts)
    if ts is not None:
        m.daily_role_usage.setdefault((ts.date().isoformat(),) + role_key, Counter()).update(counts)


def usage_breakdown(m):
    """Only aggregate counts, dates, source and model names leave the scanner."""
    def row(key, counts, daily=False, role=False):
        source, model = key[-2:]
        data = dict(counts)
        data.update(source=source, model=model,
                    total_tokens=counts['input_tokens'] + counts['output_tokens'],
                    uncached_input_tokens=max(0, counts['input_tokens'] - counts['cache_read'] - counts['cache_creation']))
        if role:
            data['role'] = data.pop('model')
        if daily:
            data['date'] = key[0]
        return data
    return {
        'models': [row(key, counts) for key, counts in sorted(m.model_usage.items())],
        'daily': [row(key, counts, True) for key, counts in sorted(m.daily_model_usage.items())],
        'roles': [row(key, counts, role=True) for key, counts in sorted(m.role_usage.items())],
        'daily_roles': [row(key, counts, True, True) for key, counts in sorted(m.daily_role_usage.items())],
        'timezone': 'UTC',
    }


def _claude_exit_code(block):
    content = block.get('content')
    if isinstance(content, list):
        content = next((b.get('text') for b in content if isinstance(b, dict) and isinstance(b.get('text'), str)), None)
    match = re.match(r'Exit code (\d+)\b', content) if block.get('is_error') is True and isinstance(content, str) else None
    return int(match[1]) if match else None


def scan(claude_dir: Path, since=None, until=None, project_dir=None, progress=None) -> Metrics:
    m = Metrics('claude')
    m.project_filtered = project_dir is not None
    project_dir = Path(project_dir).expanduser().resolve() if project_dir is not None else None
    seen = set()
    message_usage = {}
    for path in _paths(claude_dir / 'projects', '*.jsonl', m):
        m.files_scanned += 1
        if progress is not None:
            progress(m.files_scanned)
        has_data = has_sidechain = False
        cwd = None
        for rec in _records(path, m):
            if isinstance(rec.get('cwd'), str):
                cwd = rec['cwd']
            if not project_matches(cwd, project_dir):
                m.diagnostics['project_missing_cwd' if cwd is None else 'project_outside_records'] += 1
                continue
            if rec.get('type') not in ('assistant', 'user'):
                continue
            ts = record_ts(rec)
            if not ts:
                m.diagnostics['missing_or_invalid_timestamps'] += 1
            if not _in_window(ts, since, until):
                continue
            uid = rec.get('uuid')
            if isinstance(uid, str):
                if uid in seen:
                    m.diagnostics['duplicate_records'] += 1
                    continue
                seen.add(uid)
            sidechain = bool(rec.get('isSidechain'))
            # Subagent files can share their parent's sessionId; keep flow scopes separate.
            raw_sid = rec.get('sessionId') or rec.get('session_id')
            sid = ('claude', raw_sid if isinstance(raw_sid, str) else str(path),
                   str(path) if sidechain else '')
            msg = rec.get('message')
            if not isinstance(msg, dict):
                m.diagnostics['invalid_records'] += 1
                continue
            _observe(m, ts, sid)
            has_data = True
            has_sidechain |= sidechain
            m.history.state(sid, ts, 'active', sidechain)
            if rec['type'] == 'user':
                m.user_records += 1
                m.humanish_user += int(is_human_input(rec))
                content = msg.get('content')
                tool_result = rec.get('toolUseResult')
                for block in content if isinstance(content, list) else []:
                    if not isinstance(block, dict) or block.get('type') != 'tool_result':
                        continue
                    incomplete = isinstance(tool_result, dict) and any(tool_result.get(k) for k in
                        ('interrupted', 'backgroundTaskId', 'taskId', 'timedOutAfterMs'))
                    error = block.get('is_error')
                    verdict = not error if type(error) is bool and not incomplete else None
                    m.history.result(sid, block.get('tool_use_id'), verdict, _claude_exit_code(block))
                continue
            m.assistant += 1
            m.assistant_sidechain += int(sidechain)
            if msg.get('stop_reason') == 'end_turn':
                m.history.state(sid, ts, 'ended', sidechain)
            usage = msg.get('usage')
            if isinstance(usage, dict):
                read = _count(usage.get('cache_read_input_tokens'), m)
                created = _count(usage.get('cache_creation_input_tokens'), m)
                counts = {
                    'input_tokens': _count(usage.get('input_tokens'), m) + read + created,
                    'cache_read': read, 'cache_creation': created,
                    'output_tokens': _count(usage.get('output_tokens'), m),
                }
                message_id = msg.get('id')
                if isinstance(message_id, str) and message_id:
                    # Split/streamed blocks repeat the same message's usage.
                    previous = message_usage.setdefault(message_id, {})
                    delta = {k: max(0, v - previous.get(k, 0)) for k, v in counts.items()}
                    previous.update({k: max(v, previous.get(k, 0)) for k, v in counts.items()})
                    counts = delta
                _add_usage(m, counts, msg.get('model'), ts,
                           role='subagent' if sidechain else 'executor')
            content = msg.get('content')
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'tool_use':
                    _tool(m, block.get('name'), block.get('input'), sid, sidechain, ts,
                          block.get('id'))
        m.files_with_data += int(has_data)
        m.subagent_files += int(has_sidechain)
    if project_dir is None:
        _scan_stats_cache(claude_dir, m, since, until)
    else:
        m.diagnostics['project_global_stats_excluded'] += 1
    return m


def _scan_stats_cache(claude_dir, m, since, until):
    path = claude_dir / 'stats-cache.json'
    if not path.is_file() or path.is_symlink():
        return
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        daily = data.get('dailyActivity') if isinstance(data, dict) else None
        if not isinstance(daily, list):
            raise ValueError()
    except (OSError, ValueError):
        m.diagnostics['invalid_stats_cache'] += 1
        return
    m.stats_available = True
    days = set()
    for row in daily:
        if not isinstance(row, dict):
            continue
        try:
            day = parse_date(row.get('date'))
        except (ValueError, TypeError):
            m.diagnostics['invalid_stats_rows'] += 1
            continue
        if not _in_window(day, since, until) or day in days:
            continue
        days.add(day)
        m.stats_messages += _count(row.get('messageCount'), m)
        m.stats_sessions += _count(row.get('sessionCount'), m)
        m.stats_tool_calls += _count(row.get('toolCallCount'), m)
    m.stats_days = len(days)
    if days:
        m.stats_window = f'{min(days).date()} .. {max(days).date()}'

# Local rollout files differ from the public `codex exec --json` event stream.
# Canonical response items count tool calls; mirrored event notifications do not.
def _codex_human(payload):
    text = payload.get('message')
    content = payload.get('content')
    if isinstance(content, list):
        parts = [b.get('text', '') for b in content
                 if isinstance(b, dict) and isinstance(b.get('text', ''), str)]
        text = '\n'.join(parts)
        attachment = any(isinstance(b, dict) and b.get('type') in
                         ('input_image', 'image', 'input_file') for b in content)
    else:
        attachment = bool(payload.get('images') or payload.get('local_images'))
    if not isinstance(text, str):
        return attachment
    text = text.strip()
    if text.startswith(('# AGENTS.md instructions', '<environment_context>',
                        '<permissions instructions>', '<turn_aborted>', '<recommended_plugins>',
                        '<subagent_notification>', '<system-reminder>')):
        return False
    return bool(text) or attachment


def _codex_meta(path):
    """Small first pass selects canonical streams; no raw data survives the pass."""
    meta, human_events, usage_records, turn_models = {}, False, False, {}
    cwds, canonical_calls, public_started = set(), set(), set()
    try:
        with path.open(encoding='utf-8', errors='replace') as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict):
                    continue
                if rec.get('type') == 'thread.started':
                    meta.update(id=rec.get('thread_id'), source='exec')
                    if isinstance(rec.get('cwd'), str):
                        meta['cwd'] = rec['cwd']
                        cwds.add(rec['cwd'])
                if rec.get('type') == 'item.started' and isinstance(rec.get('item'), dict):
                    if isinstance(rec['item'].get('id'), str):
                        public_started.add(rec['item']['id'])
                p = rec.get('payload')
                if not isinstance(p, dict):
                    continue
                if rec.get('type') == 'session_meta':
                    meta = {k: p.get(k) for k in ('id', 'source', 'thread_source', 'cwd', 'role')}
                if rec.get('type') in ('session_meta', 'turn_context') and isinstance(p.get('cwd'), str):
                    cwds.add(p['cwd'])
                if rec.get('type') == 'event_msg' and p.get('type') == 'user_message':
                    human_events = True
                if rec.get('type') == 'token_usage_record':
                    usage_records = True
                if rec.get('type') == 'turn_context' and isinstance(p.get('turn_id'), str):
                    turn_models[p['turn_id']] = _model_name(p.get('model'))
                if rec.get('type') == 'response_item' and p.get('type') in (
                        'function_call', 'custom_tool_call', 'local_shell_call'):
                    cid = p.get('call_id', p.get('id'))
                    if isinstance(cid, str) and cid:
                        canonical_calls.add(cid)
    except OSError:
        pass
    meta['_cwds'] = cwds
    meta['_canonical_calls'] = canonical_calls
    meta['_public_started'] = public_started
    return meta, human_events, usage_records, turn_models


def _codex_role(meta):
    """Role comes from explicit session metadata, never from a model name."""
    source, thread, role = meta.get('source'), meta.get('thread_source'), meta.get('role')
    if (role in ('auto_review', 'guardian_review') or thread in ('guardian_review', 'auto_review')
            or source in ('guardian_review', 'auto_review')):
        return 'auto_review'
    if isinstance(source, dict) and 'subagent' in source:
        marker = source['subagent']
        if (isinstance(marker, str) and marker in ('guardian_review', 'auto_review')) or (
                isinstance(marker, dict) and any(key in marker for key in ('guardian_review', 'auto_review'))):
            return 'auto_review'
        return 'subagent'
    if role == 'subagent' or thread == 'subagent' or (
            isinstance(source, str) and source.lower().startswith('subagent')):
        return 'subagent'
    if role == 'executor' or source in ('cli', 'exec', 'vscode', 'app_server', 'codex_cli', 'codex_exec'):
        return 'executor'
    return 'unknown'


def _public_item_call(item):
    """Map documented JSONL item types; unknown schemas stay unsupported."""
    kind = item.get('type')
    if kind == 'command_execution' and isinstance(item.get('command'), (str, list)):
        return 'exec_command', {'cmd': item['command']}
    if kind == 'file_change' and isinstance(item.get('changes'), list):
        return 'apply_patch', {}
    if kind == 'mcp_tool_call' and isinstance(item.get('tool'), str):
        return item['tool'], item.get('arguments')
    if kind == 'collab_tool_call' and isinstance(item.get('tool'), str):
        return item['tool'], item.get('arguments')
    return None


def _public_record(rec, meta):
    """Normalize public exec JSONL to canonical data without reading command output."""
    kind, item = rec.get('type'), rec.get('item')
    if kind in ('turn.completed', 'turn.failed'):
        return {'type': 'event_msg', 'timestamp': rec.get('timestamp'), 'payload': {
            'type': 'task_complete', 'error': kind == 'turn.failed', '_public': True,
            '_usage': rec.get('usage')}}
    if kind not in ('item.started', 'item.completed') or not isinstance(item, dict):
        return None
    base = {'type': 'response_item', 'timestamp': rec.get('timestamp')}
    if item.get('type') == 'agent_message' and kind == 'item.completed':
        base['payload'] = {'type': 'message', 'role': 'assistant', 'id': item.get('id'), '_public': True}
        return base
    mapped = _public_item_call(item)
    if mapped is None:
        return None
    name, args = mapped
    cid = item.get('id')
    if kind == 'item.completed' and isinstance(cid, str) and cid in meta['_public_started']:
        base['payload'] = {'type': 'function_call_output', 'call_id': cid,
                           'output': item, '_public': True}
    else:
        base['payload'] = {'type': 'function_call', 'name': name, 'arguments': args,
                           'call_id': cid, '_public': True}
        if kind == 'item.completed':
            base['payload'].update(_result=command_verdict(item), _exit_code=exit_code(item))
    return base


def _completed_item(rec, meta):
    """Map typed completions of calls made inside code orchestration; canonical mirrors share the call id."""
    p = rec['payload']
    item = p.get('item')
    if not isinstance(item, dict):
        return None
    cid, kind = item.get('id'), item.get('type')
    if not isinstance(cid, str) or not cid or cid in meta['_canonical_calls']:
        return None
    ts = rec.get('timestamp')
    if (kind == 'CommandExecution' and isinstance(item.get('command'), (str, list))
            and item.get('status') in ('completed', 'failed')):
        # Background commands can complete after a later edit; ordering uses the start time.
        started = p.get('started_at_ms')
        if type(started) is int and started >= 0:
            try:
                ts = datetime.fromtimestamp(started / 1000, timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError):
                pass
        payload = {'name': 'exec_command', 'arguments': {'cmd': item['command']},
                   '_result': command_verdict(item), '_exit_code': exit_code(item)}
    elif (kind == 'FileChange' and isinstance(item.get('changes'), (dict, list))
            and item.get('status') == 'completed'):
        payload = {'name': 'apply_patch', 'arguments': {}}
    else:
        return None
    payload.update(type='function_call', call_id=cid, _structured=True, _nested=True)
    return {'type': 'response_item', 'timestamp': ts, 'payload': payload}


def _structured_event(rec, meta):
    """Use typed begin/end notifications only when canonical calls are absent."""
    p = rec.get('payload')
    if rec.get('type') != 'event_msg' or not isinstance(p, dict):
        return None
    kind, cid = p.get('type'), p.get('call_id')
    if kind == 'item_completed':
        return _completed_item(rec, meta)
    if kind not in ('exec_command_begin', 'exec_command_end', 'tool_call_begin', 'tool_call_end'):
        return None
    if not isinstance(cid, str) or not cid or cid in meta['_canonical_calls']:
        return None
    payload = {'call_id': cid, '_structured': True,
               'parent_call_id': p.get('parent_call_id')}
    if kind.endswith('_begin'):
        if kind == 'exec_command_begin':
            name, args = 'exec_command', {'command': p.get('command', p.get('cmd'))}
        else:
            name, args = p.get('name', p.get('tool_name')), p.get('arguments', p.get('input'))
        if not isinstance(name, str):
            return None
        payload.update(type='function_call', name=name, arguments=args)
    else:
        payload.update(type='function_call_output', output=p.get('output', p))
    return {'type': 'response_item', 'timestamp': rec.get('timestamp'), 'payload': payload}


def _nested_trace(m, p, sid, sidechain, ts, seen_calls):
    """Read explicit nested trace arrays. JavaScript and free text remain opaque."""
    data = p.get('output') if isinstance(p.get('output'), dict) else p
    nested = data.get('nested_tool_calls')
    if not isinstance(nested, list):
        return
    parent = p.get('call_id', p.get('id'))
    complete = data.get('nested_tool_calls_complete') is True
    valid = True
    for item in nested:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str):
            valid = False
            m.diagnostics['invalid_nested_tool_events'] += 1
            continue
        cid = item.get('call_id', item.get('id'))
        if not isinstance(cid, str) or not cid or cid == parent:
            valid = False
            m.diagnostics['invalid_nested_tool_events'] += 1
            continue
        key = sid, cid
        if key in seen_calls:
            if 'output' in item:
                m.history.result(sid, cid, command_verdict(item['output']), exit_code(item['output']))
            continue
        args = item.get('arguments', item.get('input'))
        if isinstance(args, str) and item.get('type') != 'custom_tool_call':
            try:
                args = json.loads(args)
            except ValueError:
                m.diagnostics['invalid_tool_arguments'] += 1
                args = {}
        # Parent completion time cannot prove when a nested call occurred.
        nested_ts = record_ts(item)
        if nested_ts is None:
            m.diagnostics['missing_or_invalid_timestamps'] += 1
        seen_calls.add(key)
        _tool(m, item['name'], args, sid, sidechain, nested_ts, cid)
        m.diagnostics['structured_nested_tool_calls'] += 1
        if 'output' in item:
            m.history.result(sid, cid, command_verdict(item['output']), exit_code(item['output']))
    if complete and valid and isinstance(parent, str) and parent:
        m._expanded_orchestrators.add((sid, parent))


def _codex_usage(usage, m):
    if not isinstance(usage, dict):
        return None
    return {key: _count(usage.get(key), m) for key in
            ('input_tokens', 'cached_input_tokens', 'cache_write_input_tokens', 'output_tokens',
             'reasoning_output_tokens')}


def _add_codex_usage(m, usage, model, ts, reasoning_reported=False, role='unknown'):
    _add_usage(m, {
        'input_tokens': usage['input_tokens'],
        'cache_read': usage['cached_input_tokens'],
        'cache_creation': usage['cache_write_input_tokens'],
        'output_tokens': usage['output_tokens'],
        'reasoning_output_tokens': usage['reasoning_output_tokens'],
    }, model, ts, reasoning_reported, role)


def scan_codex(codex_dir: Path, since=None, until=None, project_dir=None, progress=None) -> Metrics:
    import hashlib
    m = Metrics('codex')
    m.project_filtered = project_dir is not None
    project_dir = Path(project_dir).expanduser().resolve() if project_dir is not None else None
    seen, seen_calls, seen_usage = set(), set(), set()
    for folder in ('sessions', 'archived_sessions'):
        for path in _paths(codex_dir / folder, '*.jsonl', m):
            m.files_scanned += 1
            if progress is not None:
                progress(m.files_scanned)
            meta, human_events, usage_records, turn_models = _codex_meta(path)
            if project_dir is not None and not any(project_matches(cwd, project_dir) for cwd in meta['_cwds']):
                m.diagnostics['project_outside_files' if meta['_cwds'] else 'project_missing_cwd_files'] += 1
                continue
            current_cwd = meta.get('cwd')
            source = meta.get('source')
            role = _codex_role(meta)
            sidechain = role in ('subagent', 'auto_review')
            sid = ('codex', meta.get('id') if isinstance(meta.get('id'), str) else str(path))
            previous_usage = {}
            current_model = 'unknown'
            has_data = False
            for record_index, rec in enumerate(_records(path, m)):
                normalized = _public_record(rec, meta) or _structured_event(rec, meta)
                if normalized is not None:
                    rec = normalized
                    if rec['payload'].get('_public'):
                        rec['payload']['_public_index'] = record_index
                p = rec.get('payload')
                if not isinstance(p, dict):
                    if rec.get('type') == 'thread.started':
                        continue
                    m.diagnostics['unsupported_records'] += 1
                    continue
                kind, ptype = rec.get('type'), p.get('type')
                ts = record_ts(rec)
                if ts is None and kind in ('response_item', 'event_msg', 'token_usage_record'):
                    m.diagnostics['missing_or_invalid_timestamps'] += 1
                in_window = _in_window(ts, since, until)
                if kind == 'turn_context':
                    if isinstance(p.get('cwd'), str):
                        current_cwd = p['cwd']
                    current_model = _model_name(p.get('model'))
                    continue
                if kind == 'event_msg' and ptype == 'token_count' and not usage_records:
                    info = p.get('info')
                    total = _codex_usage(info.get('total_token_usage'), m) if isinstance(info, dict) else None
                    if total is None:
                        continue
                    if 'reasoning_output_tokens' not in info['total_token_usage']:
                        total['reasoning_output_tokens'] = previous_usage.get('reasoning_output_tokens', 0)
                    if any(total[k] < previous_usage.get(k, 0) for k in total
                           if k != 'reasoning_output_tokens'):
                        m.diagnostics['token_counter_resets'] += 1
                        previous_usage = {}
                        if 'reasoning_output_tokens' not in info['total_token_usage']:
                            total['reasoning_output_tokens'] = 0
                    delta = {k: max(0, v - previous_usage.get(k, 0)) for k, v in total.items()}
                    previous_usage = total
                    # Baseline advances even for records before --since.
                    key = (sid, tuple(total.items()), rec.get('timestamp'))
                    if in_window and project_matches(current_cwd, project_dir) and key not in seen_usage:
                        _add_codex_usage(m, delta, current_model, ts,
                                         'reasoning_output_tokens' in info['total_token_usage'], role)
                        seen_usage.add(key)
                    continue
                if not in_window or not project_matches(current_cwd, project_dir):
                    continue
                if p.get('_public') and isinstance(p.get('_usage'), dict):
                    usage = _codex_usage(p['_usage'], m)
                    key = (sid, 'public_usage', hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).digest())
                    if key not in seen_usage:
                        _add_codex_usage(m, usage, current_model, ts,
                                         'reasoning_output_tokens' in p['_usage'], role)
                        seen_usage.add(key)
                if kind == 'event_msg' and ptype in ('task_complete', 'turn_aborted', 'task_started'):
                    status = ('interrupted' if ptype == 'turn_aborted' or p.get('error') else
                              'ended' if ptype == 'task_complete' else 'active')
                    m.history.state(sid, ts, status, sidechain,
                                    (ptype, p.get('turn_id'), rec.get('timestamp'), p.get('_public_index')))
                if kind == 'response_item' and ptype in ('function_call_output', 'custom_tool_call_output'):
                    m.history.result(sid, p.get('call_id'), command_verdict(p.get('output')),
                                     exit_code(p.get('output')))
                    _nested_trace(m, p, sid, sidechain, ts, seen_calls)
                if kind == 'token_usage_record':
                    usage = _codex_usage(p.get('usage'), m)
                    response_id = p.get('response_id')
                    key = response_id if isinstance(response_id, str) else (
                        sid, rec.get('timestamp'), json.dumps(usage, sort_keys=True))
                    if usage and key not in seen_usage:
                        model = p.get('model')
                        if not isinstance(model, str) or not model.strip():
                            turn_id = p.get('turn_id')
                            model = turn_models.get(turn_id, 'unknown') if isinstance(turn_id, str) else current_model
                        _add_codex_usage(m, usage, model, ts,
                                         'reasoning_output_tokens' in p['usage'], role)
                        seen_usage.add(key)
                    continue
                is_human = ((kind == 'event_msg' and ptype == 'user_message') or
                            (not human_events and kind == 'response_item' and
                             ptype == 'message' and p.get('role') == 'user'))
                is_assistant = kind == 'response_item' and ptype == 'message' and p.get('role') == 'assistant'
                is_call = kind == 'response_item' and ptype in (
                    'function_call', 'custom_tool_call', 'local_shell_call', 'web_search_call', 'image_generation_call')
                if not (is_human or is_assistant or is_call):
                    continue
                if is_human and not _codex_human(p):
                    continue
                # Hashes permit replay deduplication without retaining or exposing raw text.
                fingerprint = hashlib.sha256(json.dumps(
                    [sid, rec.get('timestamp'), kind, p], sort_keys=True).encode()).digest()
                if fingerprint in seen:
                    m.diagnostics['duplicate_records'] += 1
                    continue
                seen.add(fingerprint)
                if is_call:
                    call_id = p.get('call_id', p.get('id'))
                    if isinstance(call_id, str):
                        if (sid, call_id) in seen_calls:
                            m.diagnostics['duplicate_tool_calls'] += 1
                            continue
                        seen_calls.add((sid, call_id))
                _observe(m, ts, sid)
                has_data = True
                m.history.state(sid, ts, 'active', sidechain)
                if is_human:
                    m.user_records += 1
                    m.humanish_user += int(not sidechain)
                elif is_assistant:
                    m.assistant += 1
                    m.assistant_sidechain += int(sidechain)
                else:
                    name = p.get('name')
                    args = p.get('arguments', p.get('input'))
                    if ptype == 'local_shell_call':
                        name, args = 'local_shell', p.get('action')
                    elif ptype in ('web_search_call', 'image_generation_call'):
                        name = ptype
                    if isinstance(args, str) and ptype == 'function_call':
                        try:
                            args = json.loads(args)
                        except ValueError:
                            m.diagnostics['invalid_tool_arguments'] += 1
                            args = {}
                    _tool(m, name, args, sid, sidechain, ts, p.get('call_id', p.get('id')))
                    if p.get('_public'):
                        m.diagnostics['public_jsonl_tool_calls'] += 1
                    if p.get('_structured') and (p.get('_nested') or isinstance(p.get('parent_call_id'), str)):
                        m.diagnostics['structured_nested_tool_calls'] += 1
                    if '_result' in p:
                        m.history.result(sid, p.get('call_id'), p['_result'], p.get('_exit_code'))
                    _nested_trace(m, p, sid, sidechain, ts, seen_calls)
            m.files_with_data += int(has_data)
            m.subagent_files += int(has_data and sidechain)
    m.diagnostics['opaque_orchestrator_calls'] = len(m._orchestrators - m._expanded_orchestrators)
    m.diagnostics['expanded_orchestrator_calls'] = len(m._orchestrators & m._expanded_orchestrators)
    return m


def merge_metrics(items):
    """Add counts, union days/sessions; derive ratios again from combined numerators."""
    merged = Metrics('combined')
    merged.sources = set()
    sums = ('files_scanned', 'files_with_data', 'records', 'assistant',
            'assistant_sidechain', 'humanish_user', 'user_records', 'subagent_files',
            'tool_calls', 'tool_calls_sidechain', 'cache_read',
            'cache_creation', 'output_tokens', 'input_tokens', 'reasoning_output_tokens', 'parse_errors', 'edit_calls',
            'stats_days', 'stats_messages', 'stats_sessions', 'stats_tool_calls')
    for m in items:
        merged.sources.update(m.sources)
        merged.history.merge(m.history)
        merged.project_filtered |= m.project_filtered
        for key in sums:
            setattr(merged, key, getattr(merged, key) + getattr(m, key))
        for attr in ('model_usage', 'daily_model_usage', 'role_usage', 'daily_role_usage'):
            for key, counts in getattr(m, attr).items():
                getattr(merged, attr).setdefault(key, Counter()).update(counts)
        for key in ('tools', 'bash', 'diagnostics'):
            getattr(merged, key).update(getattr(m, key))
        for key in ('sessions', 'days', 'engineering_sessions', 'engineering_days', 'edited_sessions',
                    '_orchestrators', '_expanded_orchestrators'):
            getattr(merged, key).update(getattr(m, key))
        merged._final_edits.update(m._final_edits)
        merged._verification_events.update(m._verification_events)
        if m.first_ts:
            merged.first_ts = min(merged.first_ts, m.first_ts) if merged.first_ts else m.first_ts
        if m.last_ts:
            merged.last_ts = max(merged.last_ts, m.last_ts) if merged.last_ts else m.last_ts
        merged.stats_available |= m.stats_available
        if m.stats_window:
            merged.stats_window = m.stats_window
    return merged
