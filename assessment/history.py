"""Conservative historical activity signals; these are not task acceptance."""
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def project_matches(cwd, project_dir):
    if project_dir is None:
        return True
    if not isinstance(cwd, str) or not cwd or not Path(cwd).is_absolute():
        return False
    try:
        Path(cwd).resolve().relative_to(project_dir)
        return True
    except (ValueError, OSError):
        return False


def command_verdict(output):
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except ValueError:
            match = re.match(r'\A(?:Chunk ID: [^\n]+\n)?Wall time: [^\n]+\n'
                             r'(?:Process exited with code|Exit code:)\s*(-?\d+)\n', output)
            return int(match[1]) == 0 if match and int(match[1]) >= 0 else None
    if isinstance(output, dict):
        code = output.get('exit_code')
        if type(code) is int and code >= 0 and not output.get('timed_out') and not output.get('session_id'):
            return code == 0
    return None


class History:
    def __init__(self):
        self.states = {}
        self.calls = set()
        self.results = {}
        self.unidentified = 0
        self.events = set()
        self.sequence = 0

    def state(self, sid, ts, status, sidechain=False, event_id=None):
        if sidechain:
            return
        if event_id is not None:
            key = sid, json.dumps(event_id, sort_keys=True)
            if key in self.events:
                return
            self.events.add(key)
        self.sequence += 1
        order = ts or datetime.min.replace(tzinfo=timezone.utc), self.sequence
        previous = self.states.get(sid)
        if previous is None or order > previous[0]:
            self.states[sid] = order, status

    def call(self, sid, call_id):
        if isinstance(call_id, str) and call_id:
            self.calls.add((sid, call_id))
        else:
            self.unidentified += 1

    def result(self, sid, call_id, verdict):
        if not isinstance(call_id, str) or not call_id:
            return
        key = sid, call_id
        if key not in self.calls or verdict is None:
            return
        if key in self.results and self.results[key] is not verdict:
            self.results[key] = None
        else:
            self.results[key] = verdict

    def summary(self):
        states = Counter(value[1] for value in self.states.values())
        passed = sum(self.results.get(key) is True for key in self.calls)
        failed = sum(self.results.get(key) is False for key in self.calls)
        total = len(self.calls) + self.unidentified
        return {'sessions': len(self.states), 'ended_sessions': states['ended'],
                'interrupted_sessions': states['interrupted'], 'open_sessions': states['active'],
                'verification_calls': total, 'verification_passed': passed,
                'verification_failed': failed, 'verification_unknown': total-passed-failed,
                'task_success_rate': None}

    def merge(self, other):
        for sid, value in other.states.items():
            if sid not in self.states or value[0] > self.states[sid][0]:
                self.states[sid] = value
        self.calls.update(other.calls)
        self.unidentified += other.unidentified
        for key, verdict in other.results.items():
            self.result(*key, verdict)


HISTORY_NOTE = ('历史会话不等于任务。结束标记仅表示会话最近一轮已结束；验证成功仅表示关联的 '
                'build/test 工具返回成功，不证明需求已验收。未见结束或结果时保持未知；不从历史日志计算任务成功率。')


def render_history(activity):
    text = ('历史日常活动（日志线索）\n'
            '主会话 {sessions}：最近记录为结束 {ended_sessions} / 中断或错误 {interrupted_sessions} / '
            '未见结束标记 {open_sessions}\n'
            '可识别验证调用 {verification_calls}：返回成功 {verification_passed} / '
            '返回失败 {verification_failed} / 结果未知 {verification_unknown}\n'.format(**activity) + HISTORY_NOTE)

    if activity.get('opaque_orchestrator_calls'):
        text += ('\n无法展开的编排调用 {} 次；其中的内部验证未纳入上述计数，'
                 '可识别验证调用为 0 不代表未执行验证。').format(activity['opaque_orchestrator_calls'])
    return text
