"""Offline, self-contained HTML reports built only from aggregate report data."""
from html import escape
import base64
import json
import re

from .references import REFERENCES, METHOD_NOTE
from .web_i18n import english_html

LABELS = {'combined': '合并统计', 'claude': 'Claude Code', 'codex': 'Codex'}
LEVELS = ['人工工程', 'AI 辅助', '交互式修改', '任务级 Agent', '持续工程流程',
          '自主交付', '系统自我改进', '受治理的递归改进']
DIAGNOSTICS = {
    'opaque_orchestrator_calls': '代码编排调用（内部工具无法可靠展开）',
    'missing_or_invalid_timestamps': '缺失或无效时间戳',
    'invalid_numeric_fields': '无效数值字段', 'invalid_records': '无效记录',
    'duplicate_records': '重复记录已剔除', 'duplicate_tool_calls': '重复工具调用已剔除',
    'unreadable_files': '无法读取的文件', 'unsupported_records': '不支持的记录结构',
    'token_counter_resets': '累计 token 计数重置', 'invalid_tool_arguments': '无效工具参数',
    'skipped_symlinks': '跳过的符号链接', 'invalid_stats_cache': '无效活动缓存',
    'invalid_stats_rows': '无效活动缓存行',
}
CSS = """
:root{color-scheme:light;--ink:#152f36;--muted:#536970;--line:#dbe5e5;--green:#087c68;--mint:#e7f6f0;--amber:#945500;--paper:#f4f7f6}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.65 system-ui,-apple-system,'Segoe UI',sans-serif}button,a{touch-action:manipulation}button{font:inherit;cursor:pointer}a{color:var(--green)}.wrap{max-width:1160px;margin:auto;padding:36px 28px 60px}.top{display:flex;justify-content:space-between;align-items:center;gap:20px}.eyebrow{font-size:11px;letter-spacing:.16em;font-weight:750;color:var(--green)}h1{font-size:32px;letter-spacing:-.04em;line-height:1.3;margin:10px 0}h2{font-size:18px;margin:0 0 18px}h3{font-size:15px;margin:0 0 12px}p{margin:8px 0}.muted{color:var(--muted)}.export{padding:10px 15px;border:1px solid var(--line);border-radius:9px;text-decoration:none;font-size:13px;white-space:nowrap}.tabs{display:flex;gap:6px;margin:28px 0 20px;padding:5px;background:#e7eeeb;border-radius:12px;width:max-content;max-width:100%}.tabs button{border:0;border-radius:8px;background:transparent;color:var(--muted);padding:10px 22px}.tabs button[aria-selected=true]{background:white;color:var(--ink);box-shadow:0 1px 5px #173a3012;font-weight:700}.hero{display:grid;grid-template-columns:1fr 1fr;gap:30px;padding:30px 34px;background:#133e40;color:white;border-radius:18px}.hero .muted{color:#bfd6d2}.hero .eyebrow{color:#96d9c8}.level{font-size:64px;line-height:1.1;font-weight:750;letter-spacing:-.04em}.level small{font-size:19px;letter-spacing:0;font-weight:500;margin-left:14px}.badge{display:inline-block;border-radius:20px;padding:4px 11px;font-size:12px;background:#e6f5ee;color:#166447;margin:12px 0 0}.badge.declared{background:#fff1d5;color:#875000}.hero-right{border-left:1px solid #ffffff26;padding-left:30px;align-self:center}.hero-right strong{font-size:17px}.metric-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:20px 0}.metric,.card{border:1px solid var(--line);background:#fff;border-radius:14px;padding:22px}.metric .value{font-size:28px;line-height:1.4;font-weight:700}.metric .label{font-size:12px;color:var(--muted)}.metric .foot{font-size:11px;color:var(--muted);margin-top:8px}.columns{display:grid;grid-template-columns:1.1fr 1fr;gap:18px;margin:18px 0}.ladder{display:grid;grid-template-columns:repeat(8,1fr);gap:7px;margin:20px 0 8px}.rung{border:1px solid var(--line);border-radius:9px;padding:12px 7px;font-size:11px;color:var(--muted)}.rung b{font-size:18px;display:block;color:var(--ink)}.rung.current{background:var(--mint);border-color:#81c9b2}.rung.declared{background:#fff5e0;border-color:#e8c57e}.table-scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}th{text-align:left;color:var(--muted);font-size:11px;font-weight:600}td,th{padding:10px 8px;border-bottom:1px solid #edf1ef}td:last-child{text-align:right}.status{white-space:nowrap;font-size:11px;color:var(--muted)}.status.ok{color:var(--green)}.status.declared{color:var(--amber)}.callout{background:#f0f7f3;border-left:3px solid #8abbaa;padding:12px 14px;font-size:12px;margin-top:16px}.callout.warn{background:#fff8e8;border-color:#d6b468}.check{display:flex;gap:10px;padding:7px 0;font-size:12px}.check .icon{color:var(--green);min-width:15px}.check.fail .icon{color:#94a19f}.check small{color:var(--muted)}details{border-top:1px solid var(--line);margin-top:16px;padding-top:12px}summary{cursor:pointer;font-size:13px;font-weight:600}.method{font-size:12px;color:var(--muted)}.method li{margin:8px 0}.footer{border-top:1px solid var(--line);margin-top:26px;padding-top:16px;font-size:11px;color:var(--muted)}[hidden]{display:none!important}:focus-visible{outline:3px solid #dd9e30;outline-offset:3px}
.method-picker{margin-top:24px;padding:18px 22px;border:1px solid var(--line);border-radius:14px;background:white}.method-picker label{font-weight:700;margin-right:10px}.method-picker select{font:inherit;color:var(--ink);background:var(--paper);padding:9px;border:1px solid var(--line);border-radius:8px;max-width:100%}[data-method-view=anthropic]{margin:20px 0}.strict-title{font-size:28px;font-weight:750;line-height:1.4}.evidence-table td:last-child{text-align:left}.eval-outcomes{min-width:660px}.eval-outcomes td{white-space:nowrap}.references{margin-top:22px}.references li{margin:12px 0}
@media(max-width:760px){.wrap{padding:22px 16px}.top{align-items:flex-start}h1{font-size:25px}.hero{grid-template-columns:1fr;padding:24px;gap:18px}.hero-right{border-left:0;border-top:1px solid #ffffff26;padding:16px 0 0}.metric-grid{grid-template-columns:repeat(2,1fr)}.metric{padding:16px}.columns{grid-template-columns:1fr}.ladder{grid-template-columns:repeat(4,1fr)}.tabs{width:100%}.tabs button{flex:1;padding:9px}.level{font-size:52px}.level small{display:block;font-size:17px;margin:8px 0}.export{font-size:11px;padding:8px}.card{padding:18px}}
@media print{body{background:white}.wrap{max-width:none;padding:0}.tabs,.export,.method-picker{display:none}.hero{print-color-adjust:exact}.card,.metric{break-inside:avoid}.columns{display:block}.card{margin-bottom:15px}}
.language-switch{max-width:1160px;margin:0 auto;padding:14px 28px 0;display:flex;justify-content:flex-end;align-items:center;gap:8px}.language-switch button{border:1px solid var(--line);border-radius:7px;background:white;color:var(--ink);padding:5px 12px}.language-switch button[aria-pressed=true]{background:var(--ink);color:white}@media(max-width:760px){.language-switch{padding:12px 16px 0}}@media print{.language-switch{display:none}}
"""
SCRIPT = """
const languageKey = 'ai-engineering-assessment-language';
for (const root of document.querySelectorAll('[data-language-panel]')) {
  const tabs = [...root.querySelectorAll('[role=tab][data-panel]')];
  function select(id) {
    tabs.forEach(tab => {
      const active = tab.dataset.panel === id;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
      root.querySelector('#' + tab.dataset.panel).hidden = !active;
    });
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => select(tab.dataset.panel));
    tab.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length - 1;
      if (next !== undefined) {event.preventDefault();select(tabs[next].dataset.panel);tabs[next].focus();}
    });
  });
  if (tabs.length) select(tabs[0].dataset.panel);
  const methodSelect = root.querySelector('.method-picker select');
  function selectMethod() {
    root.querySelectorAll('[data-method-view]').forEach(panel => {
      panel.hidden = methodSelect.value !== 'both' && panel.dataset.methodView !== methodSelect.value;
    });
  }
  if (methodSelect) {methodSelect.addEventListener('change', selectMethod);selectMethod();}
}
function setLanguage(language) {
  document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en';
  document.querySelectorAll('[data-language-panel]').forEach(panel => {
    panel.hidden = panel.dataset.languagePanel !== language;
  });
  document.querySelectorAll('[data-language]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.language === language));
  });
  try { localStorage.setItem(languageKey, language); } catch (_) {}
}
document.querySelectorAll('[data-language]').forEach(button => {
  button.addEventListener('click', () => setLanguage(button.dataset.language));
});
let savedLanguage = 'en';
try { if (localStorage.getItem(languageKey) === 'zh') savedLanguage = 'zh'; } catch (_) {}
setLanguage(savedLanguage);
"""


def e(value):
    return escape(str(value), quote=True)


def _number(value):
    return f'{value:,}' if isinstance(value, int) else str(value)


def _metric(label, value, foot):
    return f'<div class="metric"><div class="label">{e(label)}</div><div class="value">{e(value)}</div><div class="foot">{e(foot)}</div></div>'



def _period(report):
    requested = report.get('requested_window', {})
    observed = report.get('observed_window', {})
    since, until = requested.get('since'), requested.get('until')
    selection = f"{since or '不限'} 至 {until or '不限'}" if since or until else '全部日志（未限制日期）'
    if report.get('project_filter', {}).get('enabled'):
        selection += ' · 已限定项目目录及其子目录'
    start, end = observed.get('since'), observed.get('until')
    coverage = f'{start} 至 {end}' if start and end else '无有效时间记录'
    return (f'<div class="card" style="margin-bottom:20px"><strong>统计时间段：{e(selection)}</strong>'
            f'<p class="muted">实际日志覆盖：{e(coverage)} · UTC（起止日期均包含当天）</p></div>')


def _panel(name, report):
    o, scope = report['observed'], report['scope']
    level = report['current_level']
    title = '数据不足' if level is None else LEVELS[level]
    label = '—' if level is None else f'L{level}'
    declared = report['assessment_basis'] == 'self-reported'
    badge = '自报证据 · 尚未经独立核验' if declared else ('等待有效样本' if level is None else '日志行为候选 · 非能力认证')
    next_level = report['next_target']
    next_text = '收集可分析的日志样本' if next_level is None else (
        '持续审计与回归评测' if next_level == 7 and level == 7 else f'下一步 · L{next_level} {LEVELS[next_level]}')
    p = [f'<section role="tabpanel" id="panel-{e(name)}" aria-labelledby="tab-{e(name)}" tabindex="0">',
         _period(report), '<div data-method-view="levels">',
         '<div class="hero"><div><div class="eyebrow">ENGINEERING LEVELS / ' + e(LABELS[name]) + '</div>',
         f'<div class="level">{label}<small>{e(title)}</small></div>',
         f'<span class="badge {"declared" if declared else ""}">{badge}</span></div>',
         '<div class="hero-right"><strong>' + e(next_text) + '</strong>',
         f'<p class="muted">{scope["sessions"]:,} 个会话 · {scope["active_days"]} 个活跃日</p>',
         '<p class="muted">观察到的最高行为等级：' + e('未知' if report['observed_level'] is None else 'L' + str(report['observed_level'])) + '</p></div></div>',
         '<div class="metric-grid">',
         _metric('人工输入', _number(o['humanish_user']), '排除系统消息与子代理输入'),
         _metric('工具调用', _number(o['tool_calls']), f"{o['tool_per_human']:.2f} 次 / 人工输入"),
         _metric('修改 → 验证会话', _number(o['engineering_sessions']), '同一会话中先修改，再 build / test'),
         _metric('验证尝试占比', f"{o['verification_ratio']:.1%}", 'build + test / shell 调用'),
         '</div>',
         '<div class="card"><h2>等级阶梯</h2><p class="muted">L3–L4 展示行为信号；L5–L7 展示自报能力证据。L7 是可选的研究方向。</p><div class="ladder">']
    for i, text in enumerate(LEVELS):
        cls = ('declared' if declared else 'current') if level == i else ''
        p.append(f'<div class="rung {cls}"><b>L{i}</b>{e(text)}</div>')
    p.append('</div></div><div class="columns"><div class="card"><h2>等级条件与缺口</h2>')
    for key, gate in report['levels'].items():
        status = gate['status']
        status_text = {'OBSERVED': '行为信号满足', 'DECLARED': '自报证据满足', 'NOT VERIFIED': '未满足 / 前级未满足'}[status]
        p.append(f'<details {"open" if key == "L" + str(next_level) else ""}><summary>{e(key)} · <span class="status {"ok" if status == "OBSERVED" else "declared" if status == "DECLARED" else ""}">{status_text}</span></summary>')
        for check in gate['checks']:
            p.append(f'<div class="check {"" if check["pass"] else "fail"}"><span class="icon">{"✓" if check["pass"] else "○"}</span><div>{e(check["check"])}<br><small>{e(check["detail"])}</small></div></div>')
        p.append('</details>')
    if report.get('note'):
        p.append('<div class="callout">' + e(report['note']) + '</div>')
    p.append('</div><div class="card"><h2>数据覆盖与质量</h2>')
    p.append(f'<p>{scope["files_with_data"]} / {scope["files_scanned"]} 个文件包含窗口内数据</p><p>JSON 解析错误：{scope["parse_errors"]}</p>')
    for key, value in scope['diagnostics'].items():
        p.append(f'<p class="method">{e(DIAGNOSTICS.get(key, key))}：{value}</p>')
    if o['tools'].get('exec'):
        p.append('<div class="callout warn">部分工具通过代码编排执行，其内部行为未展开，修改与验证信号可能低估。</div>')
    p.append('</div></div><div class="card method"><h2>如何解读这份报告</h2><ul>')
    for note in report['limitations']:
        p.append('<li>' + e(note) + '</li>')
    p.append('<li>阈值用于控制样本量，未经跨团队校准；会话不等同于已完成任务。</li><li>仅包含聚合数字。不会展示 prompt、代码、命令原文或工具参数。</li></ul></div></div>')
    p.append(_anthropic_panel(report))
    p.append(_improvement_panel(report))
    p.append('</section>')
    return ''.join(p)


def _percent(value):
    return '—' if value is None else f'{value:.1%}'


def _interval(values):
    return '—' if values is None else ' – '.join(_percent(v) for v in values)


REASONS = {
    'acceptance_failed': '验收未通过', 'missing_or_inconsistent_evidence': '评分缺失或不一致',
    'execution_incomplete': '执行未完成 / 中断', 'conflicting_record': '记录冲突',
    'conflicting_task': '任务定义冲突', 'evidence_verification_failed': '本地证据核验失败',
    'invalid_record': '无效试验记录', 'outside_window': '试验在筛选窗口外',
}


def _anthropic_panel(report):
    r = report.get('anthropic_evaluation')
    if r is None:
        return '<div data-method-view="anthropic" class="card">缺少 Anthropic 方法评测数据。</div>'
    c, k = r['counts'], r['k']
    local = r['evidence_basis'] == 'local_checked'
    from .history import HISTORY_NOTE
    activity = r.get('historical_activity', {})
    history = ''
    if activity.get('sessions'):
        history = ('<div class="card" style="margin-bottom:20px"><h2>历史日常活动 · 完成线索</h2>'
                   '<div class="metric-grid">' +
                   _metric('主会话', activity['sessions'], '按日志会话计数，不等于任务数') +
                   _metric('最近一轮已结束', activity['ended_sessions'], '存在明确结束标记') +
                   _metric('中断或错误', activity['interrupted_sessions'], '最近状态为中断或报错') +
                   _metric('未见结束标记', activity['open_sessions'], '可能仍在进行或日志不完整') +
                   '</div><p>可识别验证调用 ' + e(activity['verification_calls']) +
                   '：返回成功 ' + e(activity['verification_passed']) +
                   ' / 返回失败 ' + e(activity['verification_failed']) +
                   ' / 结果未知 ' + e(activity['verification_unknown']) + '</p>' +
                   '<p class="method">' + e(HISTORY_NOTE) + '</p></div>')
    if activity.get('opaque_orchestrator_calls'):
        history += ('<div class="callout warn">无法展开的编排调用 ' +
                    e(activity['opaque_orchestrator_calls']) +
                    ' 次；内部验证未纳入上述计数，可识别验证调用为 0 不代表未执行验证。</div>')
    p = ['<div data-method-view="anthropic">' + history + '<div class="hero"><div>',
         '<div class="eyebrow">ANTHROPIC EVAL METHODOLOGY</div>',
         '<div class="strict-title">' + e(r['status_label']) + '</div>',
         '<span class="badge declared">任务结果评估 · 不设 L0–L7 等级</span></div>',
         '<div class="hero-right"><strong>日常验收与受控评测分别统计</strong>',
         '<p class="muted">记录成功、失败、未知与未执行，保留完整分母。</p>',
         '<p class="muted">' + ('已启用本地证据核验 · 不代表独立审计' if local else '仅有历史日志 · 尚无独立任务验收' if r['evidence_basis'] == 'logs_only' else '导入结果未核验 · 仅检查记录完整性') + '</p></div></div>',
         '<div class="metric-grid">',
         _metric('任务', c['tasks'], f"完整记录 {c['complete_tasks']} 个"),
         _metric('计划口径试验数', c['expected_trials'], f"窗口内已记录 {c['trials']} 次"),
         _metric('有评分证据的试验', c['graded_trials'], '预定 grader 与 outcome 结果一致'),
         _metric('本地证据核验', c['verified_trials'], '检查哈希、评分内容与产物关联' if local else '未启用本地核验'),
         '</div><div class="metric-grid">',
         _metric('成功', c['successful_trials'], '任务要求的评分全部通过'),
         _metric('失败', c['failed_trials'], '存在明确的验收失败结果'),
         _metric('未知', c['unknown_trials'], f"含窗口外试验 {c['outside_window_trials']} 次"),
         _metric('未执行 / 未提供', c['not_run_trials'], '计划中尚无对应试验记录'), '</div>']
    if c.get('collector_journal_trials') or c.get('session_export_trials'):
        p.append('<div class="callout">轨迹范围：采集事件日志 ' + e(c.get('collector_journal_trials', 0)) +
                 ' 次 / 会话导出 ' + e(c.get('session_export_trials', 0)) +
                 ' 次。事件日志覆盖登记、备注与验收，不等同于完整会话轨迹。</div>')
    if r.get('synthetic'):
        p.append('<div class="callout warn">虚构示例数据：仅演示格式和统计，不代表真实能力。</div>')
    if r['evidence_basis'] == 'logs_only':
        p.append('<div class="callout warn">本次只有操作日志，缺少任务验收结果。这不表示任务失败或能力为零。先登记任务和验收标准，再采集结果；历史会话不会被自动当成独立试验。</div>')
    window = r['trial_window']
    coverage = f"{window['since']} 至 {window['until']}" if window['since'] else '无有效试验日期'
    p.append('<p class="method">评测试验覆盖：' + e(coverage) + ' · UTC</p>')
    for mode, title in (('daily', '日常任务验收'), ('controlled', '受控重复评测')):
        rows = [g for g in r['groups'] if g['evaluation_mode'] == mode]
        p.append('<div class="card" style="margin-top:18px"><h2>' + title + '</h2>')
        if not rows:
            p.append('<p class="muted">尚无此类任务结果。</p>')
        for g in rows:
            o = g['outcomes']
            p.append('<h3>' + e(g['label']) + ' · ' + e(LABELS[g['source']]) + '</h3>')
            p.append(f'<p class="method">任务 {g["tasks"]} · 完整任务 {g["complete_tasks"]} · 成功 {o["success"]} / 失败 {o["failure"]} / 未知 {o["unknown"]} / 未执行 {o["not_run"]}</p>')
            p.append('<div class="table-scroll"><table class="eval-outcomes"><thead><tr><th>评分覆盖率</th><th>已评分通过率</th><th>计划口径成功率上下界</th>')
            if mode == 'daily':
                p.append('<th>完整任务验收率</th><th>95% Wilson 区间</th></tr></thead><tbody><tr>')
                tail = '<td>' + _percent(g['daily_success_rate']) + '</td><td>' + _interval(g['daily_wilson_95']) + '</td>'
            else:
                p.append(f'<th>pass@1</th><th>pass@{k}</th><th>pass^{k}</th></tr></thead><tbody><tr>')
                tail = ''.join('<td>' + _percent(g[key]) + '</td>' for key in ('pass_at_1', 'pass_at_k', 'pass_power_k'))
            p.append('<td>' + _percent(g['coverage']) + '</td><td>' + _percent(g['observed_success_rate']) +
                     '</td><td>' + _interval(g['success_bounds']) + '</td>' + tail + '</tr></tbody></table></div>')
            duration, human = g['duration_seconds'], g['human_interventions']
            elapsed = f"{duration['total']:.1f} 秒 / {duration['recorded']} 次记录" if duration['recorded'] else '未记录'
            interventions = f"{human['total']:g} 次 / {human['recorded']} 次记录" if human['recorded'] else '未记录'
            p.append('<p class="method">本地核验证据：' + str(o['verified']) + ' 次 · 用时：' + elapsed + ' · 人工干预：' + interventions + '</p>')
        if mode == 'daily':
            p.append('<p class="method">日常任务一次验收，不要求重置环境或参考解，不计算重复可靠性。Wilson 区间仅在任务组完整时给出，并依赖独立同分布近似。</p>')
        else:
            p.append(f'<p class="method">pass@{k}：{k} 次至少成功一次；pass^{k}：{k} 次全部成功。仅对完整且重复次数足够的受控任务组计算；不同来源、模型、框架或版本不拼接试验。</p>')
        p.append('</div>')
    p.append('<div class="callout warn">已评分通过率只描述有结果的子集，可能有选择偏差。上下界将未知和未执行分别按失败 / 成功计算，按任务等权；这是缺失数据范围，不是置信区间。— 表示无法计算，不表示 0%。</div>')
    if r['failure_reasons']:
        p.append('<div class="card" style="margin-top:18px"><h2>失败与缺失原因</h2>')
        for reason, n in r['failure_reasons'].items():
            p.append('<p>' + e(REASONS.get(reason, reason)) + '：' + str(n) + '</p>')
        p.append('</div>')
    p.append('<div class="card" style="margin-top:18px"><h2>方法要求与证据覆盖</h2><div class="table-scroll"><table class="evidence-table"><thead><tr><th>评估环节</th><th>已记录 / 应记录</th><th>所需证据</th></tr></thead><tbody>')
    for row in r['readiness']:
        coverage = f"{row['present']} / {row['total']}" if row['total'] else '不适用 / 未提供'
        p.append('<tr><td>' + e(row['label']) + '</td><td>' + coverage + '</td><td>' + e(row['requirement']) + '</td></tr>')
    p.append('</tbody></table></div><p class="method">字段覆盖与本地证据核验分开计数；引用存在不代表需求已被充分测试。人工复核单独展示。</p></div>')
    if r['diagnostics']:
        p.append('<div class="callout warn">导入数据诊断：' + e(json.dumps(r['diagnostics'], ensure_ascii=False)) + '。冲突或异常记录局部隔离；无法归属的无效任务不进入各组分母。</div>')
    p.append('<details class="card method"><summary>计分条件、限制与方法来源</summary><ul>')
    p.extend('<li>' + e(note) + '</li>' for note in r['limitations'])
    p.append('</ul><a href="' + e(r['reference_url']) + '">阅读 Anthropic 官方评估方法 ↗</a></details></div>')
    return ''.join(p)


def _improvement_panel(report):
    r = report.get('self_improvement_evaluation')
    if r is None:
        return '<div data-method-view="improvement" class="card">缺少自我改进对照数据。</div>'
    p = ['<div data-method-view="improvement"><div class="card"><h2>本地自我改进对照</h2>',
         '<p class="method">固定任务与评分器，比较改进前后版本的无人干预验收结果。'
         '此视图不自动提升 L6，也不代表独立执行或官方认证。</p>']
    if not r['comparisons']:
        p.append('<div class="callout warn">尚无预先定义的改进前后受控对照；不能从 L6 自报字段推断实际改进。</div>')
    for row in r['comparisons']:
        p.append('<h3>' + e(row['label']) + ' · ' + e(LABELS.get(row['source'], row['source'])) + '</h3>')
        p.append('<p>状态：' + e(row['status']) + '</p>')
        if row['reason']:
            p.append('<p class="method">证据缺口：' + e(row['reason']) + '</p>')
            continue
        p.append('<p>任务 ' + e(row['tasks']) + ' · 每版本试验 ' + e(row['trials_per_variant']) +
                 ' · 无人干预成功率 ' + _percent(row['baseline_autonomous']) + ' → ' +
                 _percent(row['candidate_autonomous']) + '（' + e(f"{row['autonomous_delta']:+.1%}") + '）</p>')
        p.append('<p class="method">总体成功率 ' + _percent(row['baseline_success']) + ' → ' +
                 _percent(row['candidate_success']) + ' · 改善/退步/不变任务 ' +
                 e(f"{row['improved_tasks']}/{row['regressed_tasks']}/{row['unchanged_tasks']}") +
                 ' · 符号检验 p=' + e(row['sign_test_p'] if row['sign_test_p'] is not None else '不适用') + '</p>')
    p.append('<div class="callout warn">本地核验不等于独立执行；需由外部评测方控制任务集、运行及证据保管。</div>')
    p.append('<details class="method"><summary>判定限制</summary><ul>')
    p.extend('<li>' + e(note) + '</li>' for note in r['limitations'])
    p.append('</ul></details></div></div>')
    return ''.join(p)


def _references():
    return (f'<details class="card references method"><summary>参考论文与官方文档 · {len(REFERENCES)} 项</summary>'
            '<p>' + e(METHOD_NOTE) + '</p><ul>' + ''.join(
                '<li><a href="' + e(ref['url']) + '">' + e(ref['title']) + '</a> · ' +
                e(ref['publisher']) + '<br>' + e(ref['scope']) + '</li>' for ref in REFERENCES) + '</ul></details>')


def render_html(bundle, default_method='both'):
    reports = bundle['reports']
    report_name = bundle.get('report_name', 'AI Engineering Assessment')
    report_file_stem = bundle.get('report_file_stem', 'ai-engineering-assessment')
    method_options = ''.join(
        '<option value="' + value + '"' + (' selected' if value == default_method else '') + '>' + label + '</option>'
        for value, label in (('levels', '工程等级 L0–L7 · 经验模型'),
                             ('anthropic', 'Anthropic 方法 · 严格证据'),
                             ('improvement', '自我改进 · 前后对照'), ('both', '全部同时查看')))
    payload = base64.b64encode(json.dumps(bundle, ensure_ascii=False, indent=2).encode()).decode()
    generated = next(iter(reports.values()))['generated_at'] if reports else ''
    parts = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             '<title>' + e(report_name) + '</title>',
             '<style>' + CSS + '</style></head><body><main class="wrap">',
             '<header class="top"><div><div class="eyebrow">LOCAL INSIGHTS / THREE VIEWS</div><h1>' + e(report_name) + '</h1>',
             '<p class="muted">一次查看工程等级、任务结果与自我改进对照。</p></div>',
             f'<a class="export" download="{e(report_file_stem)}.json" href="data:application/json;base64,{payload}">导出 JSON ↗</a></header>',
             '<div class="method-picker"><label for="assessment-method">评估方法</label> '
             '<select id="assessment-method">' + method_options + '</select>'
             '<p class="method">' + e(METHOD_NOTE) + '</p></div>',
             '<nav class="tabs" role="tablist" aria-label="统计来源">']
    for i, name in enumerate(reports):
        parts.append(f'<button role="tab" id="tab-{e(name)}" aria-controls="panel-{e(name)}" data-panel="panel-{e(name)}" aria-selected="{str(i == 0).lower()}">{e(LABELS[name])}</button>')
    parts.append('</nav><noscript><p>JavaScript 未启用，以下依次展示全部来源和三项评估。</p></noscript>')
    parts.extend(_panel(name, report) for name, report in reports.items())
    parts.append(_references())
    parts.append('<footer class="footer">' + e(bundle['merge_note']) + '<br>离线报告 · 无外部资源 / 无数据上传 · Ruleset ' + e(bundle['ruleset_version']) + ' · ' + e(generated) + '</footer>')
    parts.append('</main><script>' + SCRIPT + '</script></body></html>')
    chinese = ''.join(parts)
    open_main = '<main class="wrap">'
    body_start = chinese.index(open_main) + len(open_main)
    body_end = chinese.index('</main><script>', body_start)
    head = chinese[:chinese.index('<body>')].replace('lang="zh-CN"', 'lang="en"')
    content = chinese[body_start:body_end]
    english = english_html(content)
    chinese_content = re.sub(
        r'(?P<attribute>\bid|\bfor|\baria-labelledby|\baria-controls|\bdata-panel)="(?P<value>[^"]+)"',
        lambda match: match.group('attribute') + '="zh-' + match.group('value') + '"', content)
    switch = ('<div class="language-switch" role="group" aria-label="Language / 语言">'
              '<button type="button" data-language="en" aria-pressed="true">English</button>'
              '<button type="button" data-language="zh" aria-pressed="false">中文</button></div>')
    return (head + '<body>' + switch + '<main class="wrap" data-language-panel="en">' + english +
            '</main><main class="wrap" data-language-panel="zh" hidden>' + chinese_content +
            '</main><script>' + SCRIPT + '</script></body></html>')
