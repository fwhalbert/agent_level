"""Offline, self-contained HTML reports built only from aggregate report data."""
from html import escape
import base64
import json

from .references import REFERENCES, METHOD_NOTE
from .anthropic import REASONS
from .history import HISTORY_NOTE
from .web_i18n import attributes as language_attributes, pair, text as t
from .web_usage import CSS as USAGE_CSS, SCRIPT as USAGE_SCRIPT, render_usage

LABELS = {'claude': 'Claude Code', 'codex': 'Codex', 'combined': 'Combined'}
LEVELS = ['Manual engineering', 'AI-assisted coding', 'Interactive AI coding', 'Agent coding', 'Agent-first engineering',
          'Autonomous engineering', 'Self-improving engineering system', 'Governed recursive self-improvement']
DIAGNOSTICS = {
    'opaque_orchestrator_calls': 'Code orchestration calls (internal tools cannot be expanded reliably)',
    'missing_or_invalid_timestamps': 'Missing or invalid timestamps',
    'invalid_numeric_fields': 'Invalid numeric fields', 'invalid_records': 'Invalid records',
    'duplicate_records': 'Duplicate records removed', 'duplicate_tool_calls': 'Duplicate tool calls removed',
    'unreadable_files': 'Unreadable files', 'unsupported_records': 'Unsupported record structure',
    'token_counter_resets': 'Cumulative token counter resets', 'invalid_tool_arguments': 'Invalid tool arguments',
    'skipped_symlinks': 'Skipped symlinks', 'invalid_stats_cache': 'Invalid activity cache',
    'invalid_stats_rows': 'Invalid activity cache rows',
}
CSS = """
:root{color-scheme:light;--ink:#202124;--muted:#62666d;--line:#e2e4e7;--green:#087c68;--amber:#936000;--red:#b3332b;--accent:#2459a9}
*{box-sizing:border-box}
body{margin:0;background:#fff;color:var(--ink);font:15px/1.6 system-ui,-apple-system,'Segoe UI',sans-serif}
button,a,select,summary{touch-action:manipulation}button,select{font:inherit}button,summary{cursor:pointer}a{color:var(--accent);text-underline-offset:3px}
.wrap{max-width:1160px;margin:auto;padding:32px 32px 48px}.top{display:flex;justify-content:space-between;align-items:center;gap:24px}
h1{font-size:26px;line-height:1.3;letter-spacing:-.03em;margin:0}h2{font-size:18px;margin:0 0 16px}h3{font-size:15px;margin:20px 0 8px}p{margin:8px 0}
.muted,.method{color:var(--muted)}.method{font-size:13px}.method li{margin:8px 0}.eyebrow{font-size:13px;font-weight:600;color:var(--muted)}
.header-actions{display:flex;align-items:center;gap:20px;flex-shrink:0}.language-picker{display:flex;align-items:center;gap:8px;font-size:13px}
select{color:var(--ink);background:white;padding:7px 10px;border:1px solid #bfc3c9;border-radius:4px;max-width:100%}.export{font-size:13px;white-space:nowrap}
.method-picker{display:flex;align-items:center;gap:12px;margin:26px 0 10px;font-size:14px}.method-picker label{font-weight:600}
.tabs{display:flex;gap:28px;border-bottom:1px solid var(--line);margin:0 0 16px}.tabs button{border:0;border-bottom:2px solid transparent;background:none;color:var(--muted);padding:12px 0;margin-bottom:-1px}
.tabs button[aria-selected=true]{border-bottom-color:var(--ink);color:var(--ink);font-weight:700}.tabs button:hover{color:var(--accent)}
.period{font-size:12px;color:var(--muted);margin-bottom:24px}.period strong{font-weight:500}.period p{margin:3px 0}
.hero{display:grid;grid-template-columns:1.15fr 1fr;gap:36px;padding:8px 0 28px}.hero>div{min-width:0}.level{display:flex;align-items:baseline;flex-wrap:wrap;gap:8px 18px;font-size:76px;line-height:1.15;font-weight:750;letter-spacing:-.05em;margin:8px 0}
.level-code{color:var(--green)}
.level small{font-size:22px;letter-spacing:0;font-weight:600}.badge{display:block;font-size:12px;color:var(--muted);margin-top:10px}
.hero-right{border-left:1px solid var(--line);padding-left:28px;align-self:center;font-size:13px}.hero-right strong{font-size:20px;line-height:1.5}.hero-right p{margin:6px 0}.strict-title{font-size:30px;font-weight:700;line-height:1.35;margin:10px 0;letter-spacing:-.02em}
.metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin:0 0 28px;padding:20px 0;gap:0}
.metric{min-width:0;padding:0 20px;border-left:1px solid var(--line)}.metric:first-child{padding-left:0;border-left:0}.metric:last-child{padding-right:0}.metric .value{font-size:36px;line-height:1.3;font-weight:700;letter-spacing:-.03em;font-variant-numeric:tabular-nums;margin:5px 0;overflow-wrap:anywhere}
.metric .label{font-size:13px;font-weight:600}.metric .foot{font-size:12px;color:var(--muted);line-height:1.5}.metric.success .value{color:var(--green)}.metric.failure .value{color:var(--red)}.metric.warning .value{color:var(--amber)}
.metric-grid.secondary .value{font-size:26px}.metric-grid.secondary{border-top:0;padding-top:0}
.card{border-top:1px solid var(--line);padding:24px 0;margin-top:24px}.columns{display:grid;grid-template-columns:1.2fr 1fr;gap:40px}.columns>div{min-width:0}.columns .card{margin-top:0}
.ladder{display:grid;grid-template-columns:repeat(8,minmax(0,1fr));margin:20px 0 0;gap:8px}.rung{border:0;border-top:3px solid var(--line);background:transparent;text-align:left;padding:10px 8px;font-size:12px;color:var(--muted);overflow-wrap:anywhere}.rung b{font-size:18px;display:block;color:var(--ink);margin-bottom:4px}.rung.achieved{border-color:var(--green);color:var(--green)}.rung.achieved b{color:var(--green)}.rung.current{background:#e7f6f0;box-shadow:inset 0 0 0 1px #81c9b2}.rung[aria-expanded=true]{outline:2px solid var(--line);outline-offset:2px}.rung-state{display:block;font-size:11px;margin-top:8px}.rung-state:after{content:' ▾'}.rung[aria-expanded=true] .rung-state:after{content:' ▴'}
.level-branch{margin:20px 0 0;padding:16px 20px;border-left:2px solid var(--line);background:#fafbfa}.level-branch h3{margin:0 0 8px}.level-branch .check{position:relative;margin-left:8px;padding-left:18px;border-left:1px solid var(--line)}.level-branch .check:before{content:'';position:absolute;left:0;top:20px;width:12px;border-top:1px solid var(--line)}
.metric-grid.engineering{grid-template-columns:repeat(5,minmax(0,1fr))}.metric.coverage .value{font-size:26px}.coverage details{font-size:12px;margin-top:8px;padding-top:8px}.coverage summary{font-size:12px}.coverage .method{font-size:12px}
.table-scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}th{text-align:left;color:var(--muted);font-size:12px;font-weight:500}td,th{padding:12px 10px;border-bottom:1px solid var(--line)}td:last-child{text-align:right}.evidence-table td:last-child{text-align:left}.eval-outcomes{min-width:660px}.eval-outcomes td{white-space:nowrap;font-size:20px;font-weight:600}
.status{font-size:12px;color:var(--muted)}.status.ok{color:var(--green);font-weight:600}.comparison-status{font-size:20px;font-weight:650}.comparison-result{font-size:24px;font-weight:650;line-height:1.5;font-variant-numeric:tabular-nums}
.callout{border-left:3px solid #abb2bc;padding:10px 14px;font-size:13px;margin:16px 0;color:var(--muted);background:#f7f8fa}.callout.warn{border-color:var(--amber);background:#fcf8ef;color:#795117}
.check{display:flex;gap:10px;padding:9px 0;font-size:14px}.check .icon{color:var(--green);min-width:16px;font-weight:700}.check.fail .icon{color:var(--amber)}.check.fail{font-weight:600}.check small{color:var(--muted);font-size:12px;font-weight:400}
details{border-top:1px solid var(--line);margin-top:14px;padding-top:14px}summary{font-size:14px;font-weight:600;color:var(--ink)}details[open]>summary{margin-bottom:12px}.references{margin-top:24px}.references li{margin:12px 0}.footer{border-top:1px solid var(--line);margin-top:24px;padding-top:16px;font-size:12px;color:var(--muted)}
[hidden]{display:none!important}:focus-visible{outline:2px solid var(--accent);outline-offset:4px}
@media(max-width:760px){.wrap{padding:24px 18px}.top{align-items:flex-start;flex-wrap:wrap;gap:16px}h1{font-size:23px}.header-actions{width:100%;justify-content:space-between}.method-picker{flex-wrap:wrap;gap:6px;margin-top:22px}.method-picker select{width:100%}.tabs{gap:24px}.tabs button{font-size:14px}.hero{grid-template-columns:1fr;gap:20px;padding-bottom:24px}.hero-right{border-left:0;border-top:1px solid var(--line);padding:16px 0 0}.hero-right strong{font-size:18px}.level{font-size:64px}.level small{font-size:20px}.strict-title{font-size:26px}.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr));row-gap:22px}.metric:nth-child(odd){padding-left:0;border-left:0}.metric:nth-child(even){padding-right:0}.metric .value{font-size:32px}.columns{grid-template-columns:1fr;gap:0}.ladder{grid-template-columns:repeat(4,minmax(0,1fr))}.comparison-result{font-size:20px}}
@media print{.wrap{max-width:none;padding:0}.tabs,.export,.method-picker,.language-picker{display:none}.hero,.metric-grid,.rung,.callout{print-color-adjust:exact}.hero,.metric{break-inside:avoid}.columns{display:block}.card{margin-bottom:15px}}
@media(max-width:760px){.metric-grid.engineering{grid-template-columns:repeat(2,minmax(0,1fr))}.metric.coverage{grid-column:1/-1;border-top:1px solid var(--line);padding-top:18px}.level-branch{padding:14px 12px}}
@media print{.level-branch[hidden]{display:block!important}}
"""
CSS += USAGE_CSS
SCRIPT = """
{
  const root = document.querySelector('main');
  const languageSelect = root.querySelector('#report-language');
  function selectLanguage(language) {
    const lang = language === 'zh' ? 'zh' : 'en';
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
    languageSelect.value = lang;
    document.querySelectorAll('[data-en][data-zh]').forEach(element => {
      element.textContent = element.dataset[lang];
    });
    root.querySelectorAll('[data-aria-en][data-aria-zh]').forEach(element => {
      element.setAttribute('aria-label', element.dataset[lang === 'zh' ? 'ariaZh' : 'ariaEn']);
    });
  }
  let savedLanguage = 'en';
  try {savedLanguage = localStorage.getItem('agent-level-language') || 'en';} catch (_) {}
  selectLanguage(savedLanguage);
  languageSelect.addEventListener('change', () => {
    selectLanguage(languageSelect.value);
    try {localStorage.setItem('agent-level-language', languageSelect.value);} catch (_) {}
  });
""" + USAGE_SCRIPT + """
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
  root.querySelectorAll('.level-explorer').forEach(explorer => {
    const buttons = [...explorer.querySelectorAll('.rung')];
    buttons.forEach(button => button.addEventListener('click', () => {
      const expand = button.getAttribute('aria-expanded') !== 'true';
      buttons.forEach(item => {
        const active = item === button && expand;
        item.setAttribute('aria-expanded', String(active));
        root.querySelector('#' + item.getAttribute('aria-controls')).hidden = !active;
      });
    }));
  });
  const methodSelect = root.querySelector('.method-picker select');
  function selectMethod() {
    root.querySelectorAll('[data-method-view]').forEach(panel => {
      panel.hidden = methodSelect.value !== 'both' && panel.dataset.methodView !== methodSelect.value;
    });
  }
  if (methodSelect) {methodSelect.addEventListener('change', selectMethod);selectMethod();}
}
"""


def e(value):
    return escape(str(value), quote=True)


def _number(value):
    return f'{value:,}' if isinstance(value, int) else str(value)


def _metric(label, value, foot, *, tone="", **values):
    return f'<div class="metric{(" " + e(tone)) if tone else ""}"><div class="label">{t(label)}</div><div class="value">{e(value)}</div><div class="foot">{t(foot, **values)}</div></div>'


def _period(report):
    requested = report.get('requested_window', {})
    observed = report.get('observed_window', {})
    since, until = requested.get('since'), requested.get('until')
    selection = (pair('{start} to {end}', start=since or pair('Any date'), end=until or pair('Any date'))
                 if since or until else pair('All logs (no date filter)'))
    if report.get('project_filter', {}).get('enabled'):
        selection = tuple(a + ' · ' + b for a, b in zip(selection, pair('Project directory and descendants only')))
    start, end = observed.get('since'), observed.get('until')
    coverage = pair('{start} to {end}', start=start, end=end) if start and end else pair('No valid timestamps')
    filters = report.get('task_filters', {})
    filter_text = tuple(' · '.join(f'{pair(label)[i]}: {filters[key]}' for key, label in
                                 (('model', 'model'), ('reasoning_effort', 'effort')) if filters.get(key))
                        for i in (0, 1))
    task_note = ('<p class="muted">' + t('Task evidence filter: {filters} (does not change the historical L0–L7 level)', filters=filter_text) + '</p>'
                 if filter_text[0] else '')
    return ('<div class="period"><strong>' + t('Selected period: {period}', period=selection) + '</strong>'
            '<p class="muted">' + t('Observed log coverage: {coverage} · UTC (both dates inclusive)', coverage=coverage) + '</p>'
            f'{task_note}</div>')


def _panel(name, report):
    o, scope = report['observed'], report['scope']
    level = report['current_level']
    title = LEVELS[level]
    badge = ('Default baseline' if report['assessment_basis'] == 'default' else
             'Log behavior candidate · Not a capability certification')
    next_level = report['next_target']
    p = [f'<section role="tabpanel" id="panel-{e(name)}" aria-labelledby="tab-{e(name)}" tabindex="0">',
         _period(report), '<div data-method-view="levels">',
         '<div class="hero"><div><div class="eyebrow">' + t('ENGINEERING LEVELS / {source}', source=pair(LABELS[name])) + '</div>',
         f'<div class="level"><span class="level-code">L{level}</span><small>{t(title)}</small></div>',
         f'<span class="badge">{t(badge)}</span></div>',
         '<div class="hero-right"><strong>' + t('Next · L{level} {title}', level=next_level, title=pair(LEVELS[next_level])) + '</strong>',
         '<p class="muted">' + t('{sessions} sessions · {days} active days', sessions=f'{scope["sessions"]:,}', days=scope['active_days']) + '</p></div></div>']
    visibility = report.get('level_visibility', {})
    if visibility.get('may_undercount_edits_and_verification'):
        p.append('<div class="callout warn">' + t('Code orchestration calls {count} have no visible nested tool trace. This level reflects visible logs only and may undercount edits and verification. See task outcome assessment for Codex acceptance results.', count=visibility['opaque_orchestrator_calls']) + '</div>')
    p.extend(['<div class="metric-grid engineering">',
              _metric('Human inputs', _number(o['humanish_user']), 'Excludes system and subagent input'),
              _metric('Tool calls', _number(o['tool_calls']), '{ratio} calls / human input', ratio=f"{o['tool_per_human']:.2f}"),
              _metric('Edit → verify sessions', _number(o['engineering_sessions']), 'Edit then build / test in the same session'),
              _metric('Verification attempt share', f"{o['verification_ratio']:.1%}", 'build + test / shell calls'),
              '<div class="metric coverage"><div class="label">' + t('Data coverage and quality') + '</div>',
              f'<div class="value">{scope["files_with_data"]:,} / {scope["files_scanned"]:,}</div>',
              '<div class="foot">' + t('Files with data / Scanned files') + '<br>' + t('JSON parse errors: {count}', count=scope['parse_errors']) + '</div>'])
    if scope['diagnostics']:
        p.append('<details><summary>' + t('Diagnostics') + '</summary>')
        for key, value in scope['diagnostics'].items():
            p.append(f'<p class="method">{t(DIAGNOSTICS.get(key, key))}: {value}</p>')
        p.append('</details>')
    p.append('</div></div>' + render_usage(name, report) + '<div class="card level-explorer"><h2>' + t('Level requirements and gaps') + '</h2><div class="ladder">')
    selected = next_level
    for i, title in enumerate(LEVELS):
        achieved = report["levels"][f"L{i}"]["status"] in ("DEFAULT", "OBSERVED")
        cls = (' achieved' if achieved else '') + (' current' if level == i else '')
        state = 'Current level' if level == i else 'Achieved' if achieved else 'Next target' if next_level == i else 'View requirements'
        p.append(f'<button type="button" class="rung{cls}" id="level-{e(name)}-{i}" aria-controls="requirements-{e(name)}-{i}" aria-expanded="{str(i == selected).lower()}"><b>L{i}</b>{t(title)}<span class="rung-state">{t(state)}</span></button>')
    p.append('</div>')
    for i, title in enumerate(LEVELS):
        gate = report['levels'][f'L{i}']
        p.append(f'<div class="level-branch" id="requirements-{e(name)}-{i}" role="region" aria-labelledby="level-{e(name)}-{i}"{ "" if i == selected else " hidden"}><h3>L{i} · {t(title)}</h3>')
        status = gate['status']
        status_text = {'DEFAULT': 'Achieved by default', 'OBSERVED': 'Behavior observed', 'NOT VERIFIED': 'Unmet / Earlier level unmet'}[status]
        p.append(f'<p class="status {"ok" if status in ("DEFAULT", "OBSERVED") else ""}">{t(status_text)}</p>')
        for check in gate['checks']:
            p.append(f'<div class="check {"" if check["pass"] else "fail"}"><span class="icon">{"✓" if check["pass"] else "○"}</span><div>{t(check["check"])}<br><small>{t(check["detail"])}</small></div></div>')
        p.append('</div>')
    if report.get('note'):
        p.append('<div class="callout">' + t(report['note']) + '</div>')
    p.append('</div></div>')
    p.append(_anthropic_panel(report))
    p.append(_improvement_panel(report))
    p.append('</section>')
    return ''.join(p)


def _percent(value):
    return '—' if value is None else f'{value:.1%}'


def _interval(values):
    return '—' if values is None else ' – '.join(_percent(v) for v in values)


def _anthropic_panel(report):
    r = report.get('anthropic_evaluation')
    if r is None:
        return '<div data-method-view="anthropic" class="card">' + t('Anthropic evaluation data is missing.') + '</div>'
    c, k = r['counts'], r['k']
    local = r['evidence_basis'] == 'local_checked'
    activity = r.get('historical_activity', {})
    p = ['<div data-method-view="anthropic">']
    basis = ('Local evidence checked · Not an independent audit' if local else
             'Historical logs only · No separate task acceptance' if r['evidence_basis'] == 'logs_only' else
             'Imported results unchecked · Record completeness only')
    p.extend([
        '<div class="hero"><div><div class="eyebrow">' + t('ANTHROPIC EVAL METHODOLOGY') + '</div>',
        '<div class="strict-title">' + t(r['status_label']) + '</div>',
        '<span class="badge">' + t('Task outcome assessment · No L0–L7 level') + '</span></div>',
        '<div class="hero-right"><strong>' + t('Daily acceptance and controlled evaluations are reported separately') + '</strong>',
        '<p class="muted">' + t('Success, failure, unknown, and unrun outcomes retain the full denominator.') + '</p>',
        '<p class="muted">' + t(basis) + '</p></div></div><div class="metric-grid">',
        _metric('Success', c['successful_trials'], 'All required graders passed', tone='success' if c['successful_trials'] else ''),
        _metric('Failure', c['failed_trials'], 'Explicit acceptance failure', tone='failure' if c['failed_trials'] else ''),
        _metric('Unknown', c['unknown_trials'], 'Out-of-window trials included: {count}', count=c['outside_window_trials'], tone='warning' if c['unknown_trials'] else ''),
        _metric('Unrun / Not supplied', c['not_run_trials'], 'No trial record for planned run', tone='warning' if c['not_run_trials'] else ''),
        '</div><div class="metric-grid secondary">',
        _metric('Tasks', c['tasks'], 'Complete records: {count}', count=c['complete_tasks']),
        _metric('Planned trials', c['expected_trials'], 'Recorded in window: {count}', count=c['trials']),
        _metric('Trials with grader evidence', c['graded_trials'], 'Planned graders agree with outcome'),
        _metric('Local evidence verification', c['verified_trials'], 'Checks hashes, grader content, and artifact links' if local else 'Local verification disabled'), '</div>',
    ])
    if c.get('collector_journal_trials') or c.get('session_export_trials'):
        p.append('<div class="callout">' + t('Trace coverage: collector journal {journals} runs / session export {exports} runs. The event journal covers registration and acceptance, not the full session transcript.', journals=c.get('collector_journal_trials', 0), exports=c.get('session_export_trials', 0)) + '</div>')
    if r.get('synthetic'):
        p.append('<div class="callout warn">' + t('Synthetic example data illustrates the format and statistics; it does not represent real capability.') + '</div>')
    if r['evidence_basis'] == 'logs_only':
        p.append('<div class="callout warn">' + t('Only activity logs are available, without task acceptance outcomes. This does not mean failure or zero capability. Register tasks and acceptance criteria before collecting results; historical sessions are not treated as independent trials.') + '</div>')
    window = r['trial_window']
    coverage = pair('{start} to {end}', start=window['since'], end=window['until']) if window['since'] else pair('No valid trial dates')
    p.append('<p class="method">' + t('Evaluation trial coverage: {coverage} · UTC', coverage=coverage) + '</p>')
    for mode, title in (('daily', 'Daily task acceptance'), ('controlled', 'Controlled repeat evaluation')):
        rows = [g for g in r['groups'] if g['evaluation_mode'] == mode]
        p.append('<div class="card" style="margin-top:18px"><h2>' + t(title) + '</h2>')
        if not rows:
            p.append('<p class="muted">' + t('No results for this mode yet.') + '</p>')
        for g in rows:
            o = g['outcomes']
            p.append('<h3>' + e(g['label']) + ' · ' + t(LABELS[g['source']]) + '</h3>')
            p.append('<p class="method">' + t('Tasks {tasks} · Complete tasks {complete} · Success {success} / failure {failure} / unknown {unknown} / unrun {unrun}', tasks=g['tasks'], complete=g['complete_tasks'], success=o['success'], failure=o['failure'], unknown=o['unknown'], unrun=o['not_run']) + '</p>')
            headers = ['Grading coverage', 'Graded pass rate', 'Planned success bounds']
            if mode == 'daily':
                headers += ['Complete task acceptance rate', '95% Wilson interval']
                tail = '<td>' + _percent(g['daily_success_rate']) + '</td><td>' + _interval(g['daily_wilson_95']) + '</td>'
            else:
                headers += ['pass@1', f'pass@{k}', f'pass^{k}']
                tail = ''.join('<td>' + _percent(g[key]) + '</td>' for key in ('pass_at_1', 'pass_at_k', 'pass_power_k'))
            p.append('<div class="table-scroll"><table class="eval-outcomes"><thead><tr>' + ''.join('<th>' + t(label) + '</th>' for label in headers) + '</tr></thead><tbody><tr>')
            p.append('<td>' + _percent(g['coverage']) + '</td><td>' + _percent(g['observed_success_rate']) +
                     '</td><td>' + _interval(g['success_bounds']) + '</td>' + tail + '</tr></tbody></table></div>')
            duration, human = g['duration_seconds'], g['human_interventions']
            elapsed = pair('{total} sec / {records} records', total=f"{duration['total']:.1f}", records=duration['recorded']) if duration['recorded'] else pair('Not recorded')
            interventions = pair('{total} times / {records} records', total=f"{human['total']:g}", records=human['recorded']) if human['recorded'] else pair('Not recorded')
            p.append('<p class="method">' + t('Locally verified evidence: {runs} runs · Duration: {duration} · Human interventions: {human}', runs=o['verified'], duration=elapsed, human=interventions) + '</p>')
        if mode == 'daily':
            p.append('<p class="method">' + t('Daily tasks have one acceptance run and require neither environment reset nor a reference solution. Repeat reliability is not calculated. Wilson intervals require complete groups and an approximately independent, identically distributed sample.') + '</p>')
        else:
            p.append('<p class="method">' + t('pass@{k}: at least one success in {k} runs; pass^{k}: success in all {k} runs. Calculated only for complete controlled task groups with enough repeats; trials from different sources, models, harnesses, or versions are not pooled.', k=k) + '</p>')
        p.append('</div>')
    p.append('<div class="callout warn">' + t('The graded pass rate covers only trials with results and may have selection bias. Bounds treat unknown and unrun trials as failures or successes, with equal task weights. This is a missing-data range, not a confidence interval. — means unavailable, not 0%.') + '</div>')
    if r['failure_reasons']:
        p.append('<div class="card" style="margin-top:18px"><h2>' + t('Failure and missing evidence reasons') + '</h2>')
        for reason, n in r['failure_reasons'].items():
            p.append('<p>' + t(REASONS.get(reason, reason)) + ': ' + str(n) + '</p>')
        p.append('</div>')
    p.append('<div class="card" style="margin-top:18px"><h2>' + t('Method requirements and evidence coverage') + '</h2><div class="table-scroll"><table class="evidence-table"><thead><tr>' + ''.join('<th>' + t(label) + '</th>' for label in ('Evaluation step', 'Recorded / Expected', 'Required evidence')) + '</tr></thead><tbody>')
    for row in r['readiness']:
        coverage = f"{row['present']} / {row['total']}" if row['total'] else t('Not applicable / Not supplied')
        p.append('<tr><td>' + t(row['label']) + '</td><td>' + coverage + '</td><td>' + t(row['requirement']) + '</td></tr>')
    p.append('</tbody></table></div><p class="method">' + t('Field coverage and local evidence verification are counted separately. A reference does not prove sufficient requirement coverage. Human review is shown separately.') + '</p></div>')
    if r['diagnostics']:
        p.append('<div class="callout warn">' + t('Imported data diagnostics: {diagnostics}. Conflicting or anomalous records are isolated; invalid unassigned tasks are excluded from group denominators.', diagnostics=json.dumps(r['diagnostics'], ensure_ascii=False)) + '</div>')
    if activity.get('sessions'):
        p.extend([
            '<details class="card"><summary>' + t('Historical activity · Completion signals') + '</summary><div class="metric-grid secondary">',
            _metric('Primary sessions', activity['sessions'], 'Log sessions, not task count'),
            _metric('Latest turn ended', activity['ended_sessions'], 'Explicit end marker present'),
            _metric('Interrupted or errored', activity['interrupted_sessions'], 'Latest state is interrupted or errored'),
            _metric('No end marker', activity['open_sessions'], 'May be active or incomplete logs'),
            '</div><p>' + t('Recognized verification calls {calls}: successful returns {passed} / failed returns {failed} / unknown results {unknown}',
                           calls=activity['verification_calls'], passed=activity['verification_passed'],
                           failed=activity['verification_failed'], unknown=activity['verification_unknown']) + '</p>',
            '<p class="method">' + t(HISTORY_NOTE) + '</p></details>',
        ])
    if activity.get('opaque_orchestrator_calls'):
        p.append('<div class="callout warn">' + t('Unexpanded orchestration calls {count}; internal verification is excluded from these counts. Zero recognized calls does not imply no verification.', count=activity['opaque_orchestrator_calls']) + '</div>')
    p.append('<details class="card method"><summary>' + t('Scoring rules, limitations, and method source') + '</summary><ul>')
    p.extend('<li>' + t(note) + '</li>' for note in r['limitations'])
    p.append('</ul><a href="' + e(r['reference_url']) + '">' + t('Read Anthropic’s published evaluation method ↗') + '</a></details></div>')
    return ''.join(p)


def _improvement_panel(report):
    r = report.get('self_improvement_evaluation')
    if r is None:
        return '<div data-method-view="improvement" class="card">' + t('Self-improvement comparison data is missing.') + '</div>'
    p = ['<div data-method-view="improvement"><div class="card"><h2>' + t('Local self-improvement comparison') + '</h2>',
         '<p class="method">' + t('Compare autonomous acceptance before and after a change on fixed tasks and graders. This view does not promote L6 or certify independent execution.') + '</p>']
    if r['diagnostics']:
        p.append('<div class="callout warn">' + t('Invalid improvement comparison records: {count}',
                 count=r['diagnostics']['invalid_comparisons']) + '</div>')
    elif not r['comparisons']:
        p.append('<div class="callout warn">' + t('No predefined controlled before/after comparison is available.') + '</div>')
    for row in r['comparisons']:
        p.append('<h3>' + e(row['label']) + ' · ' + t(LABELS.get(row['source'], row['source'])) + '</h3>')
        p.append('<p class="comparison-status">' + t('Status: {status}', status=pair(row['status'])) + '</p>')
        if row['reason']:
            p.append('<p class="method">' + t('Evidence gap: {reason}', reason=pair(row['reason'])) + '</p>')
            continue
        p.append('<p class="method">' + t('Tasks {tasks} · Trials per version {trials}', tasks=row['tasks'], trials=row['trials_per_variant']) + '</p>')
        p.append('<p class="comparison-result">' + t('Autonomous success rate {before} → {after} ({delta})', before=_percent(row['baseline_autonomous']), after=_percent(row['candidate_autonomous']), delta=f"{row['autonomous_delta']:+.1%}") + '</p>')
        p.append('<p class="method">' + t('Overall success rate {before} → {after} · Improved / regressed / unchanged tasks {changes} · Sign test p={p}', before=_percent(row['baseline_success']), after=_percent(row['candidate_success']), changes=f"{row['improved_tasks']}/{row['regressed_tasks']}/{row['unchanged_tasks']}", p=row['sign_test_p'] if row['sign_test_p'] is not None else 'N/A') + '</p>')
    p.append('<div class="callout warn">' + t('Local checks are not independent execution. An outside evaluator must control the task suite, runs, and evidence.') + '</div>')
    p.append('<details class="method"><summary>' + t('Interpretation limits') + '</summary><ul>')
    p.extend('<li>' + t(note) + '</li>' for note in r['limitations'])
    p.append('</ul></details></div></div>')
    return ''.join(p)


def _references():
    return ('<details class="card references method"><summary>' + t('References · {count} items', count=len(REFERENCES)) + '</summary>'
            '<p>' + t(METHOD_NOTE) + '</p><ul>' + ''.join(
                '<li><a href="' + e(ref['url']) + '">' + e(ref['title']) + '</a> · ' +
                e(ref['publisher']) + '<br>' + t(ref['scope']) + '</li>' for ref in REFERENCES) + '</ul></details>')


def render_html(bundle, default_method='levels'):
    reports = bundle['reports']
    source_order = [name for name in LABELS if name in reports]
    report_name = bundle.get('report_name', 'AI Engineering Assessment')
    report_file_stem = bundle.get('report_file_stem', 'ai-engineering-assessment')
    methods = (('levels', 'Engineering levels L0–L7 · Heuristic model'),
               ('anthropic', 'Anthropic method · Evidence based'),
               ('improvement', 'Self-improvement · Before and after'), ('both', 'Show all views'))
    if default_method not in dict(methods):
        default_method = 'levels'
    method_options = ''.join(
        '<option value="' + value + '"' + (' selected' if value == default_method else '') + ' ' + language_attributes(label) + '>' + e(label) + '</option>'
        for value, label in methods)
    payload = base64.b64encode(json.dumps(bundle, ensure_ascii=False, indent=2).encode()).decode()
    generated = next(iter(reports.values()))['generated_at'] if reports else ''
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             '<title ' + language_attributes(report_name) + '>' + e(report_name) + '</title>',
             '<style>' + CSS + '</style>',
             '<noscript><style>[role=tabpanel][hidden],[data-method-view][hidden],.level-branch[hidden]{display:block!important}.language-picker{display:none}</style></noscript>',
             '</head><body><main class="wrap">',
             '<header class="top"><div><h1>' + t(report_name) + '</h1></div>',
             '<div class="header-actions"><div class="language-picker"><label for="report-language">Language / 语言</label> '
             '<select id="report-language"><option value="en" lang="en" selected>English</option><option value="zh" lang="zh-CN">中文</option></select></div>',
             f'<a class="export" download="{e(report_file_stem)}.json" href="data:application/json;base64,{payload}">' + t('Export JSON ↗') + '</a></div></header>',
             '<div class="method-picker"><label for="assessment-method">' + t('Assessment method') + '</label> '
             '<select id="assessment-method">' + method_options + '</select>'
             '</div>',
             '<nav class="tabs" role="tablist" aria-label="Data source" data-aria-en="Data source" data-aria-zh="数据来源">']
    for i, name in enumerate(source_order):
        parts.append(f'<button role="tab" id="tab-{e(name)}" aria-controls="panel-{e(name)}" data-panel="panel-{e(name)}" aria-selected="{str(i == 0).lower()}" tabindex="{0 if i == 0 else -1}">{t(LABELS[name])}</button>')
    parts.append('</nav><noscript><p>JavaScript is disabled; all sources and three assessment views follow. / JavaScript 已禁用；下方展示所有来源及三种评估视图。</p></noscript>')
    for i, name in enumerate(source_order):
        panel = _panel(name, reports[name])
        if i:
            panel = panel.replace('<section role="tabpanel"', '<section role="tabpanel" hidden', 1)
        for method, _ in methods:
            if default_method != 'both' and method != default_method:
                panel = panel.replace(f'data-method-view="{method}"', f'data-method-view="{method}" hidden')
        parts.append(panel)
    parts.append(_references())
    parts.append('<footer class="footer">' + t(bundle['merge_note']) + '<br>' + t('Offline report · No external resources or data upload · Ruleset {version} · {generated}', version=bundle['ruleset_version'], generated=generated) + '</footer>')
    parts.append('</main><script>' + SCRIPT + '</script></body></html>')
    return ''.join(parts)
