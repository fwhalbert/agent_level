"""Offline, self-contained HTML reports built only from aggregate report data."""
from html import escape
import base64
import json

from .references import REFERENCES, METHOD_NOTE
from .anthropic import REASONS
from .history import HISTORY_NOTE

LABELS = {'combined': 'Combined', 'claude': 'Claude Code', 'codex': 'Codex'}
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
:root{color-scheme:light;--ink:#152f36;--muted:#536970;--line:#dbe5e5;--green:#087c68;--mint:#e7f6f0;--amber:#945500;--paper:#f4f7f6}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.65 system-ui,-apple-system,'Segoe UI',sans-serif}button,a{touch-action:manipulation}button{font:inherit;cursor:pointer}a{color:var(--green)}.wrap{max-width:1160px;margin:auto;padding:36px 28px 60px}.top{display:flex;justify-content:space-between;align-items:center;gap:20px}.eyebrow{font-size:11px;letter-spacing:.16em;font-weight:750;color:var(--green)}h1{font-size:32px;letter-spacing:-.04em;line-height:1.3;margin:10px 0}h2{font-size:18px;margin:0 0 18px}h3{font-size:15px;margin:0 0 12px}p{margin:8px 0}.muted{color:var(--muted)}.export{padding:10px 15px;border:1px solid var(--line);border-radius:9px;text-decoration:none;font-size:13px;white-space:nowrap}.tabs{display:flex;gap:6px;margin:28px 0 20px;padding:5px;background:#e7eeeb;border-radius:12px;width:max-content;max-width:100%}.tabs button{border:0;border-radius:8px;background:transparent;color:var(--muted);padding:10px 22px}.tabs button[aria-selected=true]{background:white;color:var(--ink);box-shadow:0 1px 5px #173a3012;font-weight:700}.hero{display:grid;grid-template-columns:1fr 1fr;gap:30px;padding:30px 34px;background:#133e40;color:white;border-radius:18px}.hero .muted{color:#bfd6d2}.hero .eyebrow{color:#96d9c8}.level{font-size:64px;line-height:1.1;font-weight:750;letter-spacing:-.04em}.level small{font-size:19px;letter-spacing:0;font-weight:500;margin-left:14px}.badge{display:inline-block;border-radius:20px;padding:4px 11px;font-size:12px;background:#e6f5ee;color:#166447;margin:12px 0 0}.badge.declared{background:#fff1d5;color:#875000}.hero-right{border-left:1px solid #ffffff26;padding-left:30px;align-self:center}.hero-right strong{font-size:17px}.metric-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:20px 0}.metric,.card{border:1px solid var(--line);background:#fff;border-radius:14px;padding:22px}.metric .value{font-size:28px;line-height:1.4;font-weight:700}.metric .label{font-size:12px;color:var(--muted)}.metric .foot{font-size:11px;color:var(--muted);margin-top:8px}.columns{display:grid;grid-template-columns:1.1fr 1fr;gap:18px;margin:18px 0}.ladder{display:grid;grid-template-columns:repeat(8,1fr);gap:7px;margin:20px 0 8px}.rung{border:1px solid var(--line);border-radius:9px;padding:12px 7px;font-size:11px;color:var(--muted)}.rung b{font-size:18px;display:block;color:var(--ink)}.rung.current{background:var(--mint);border-color:#81c9b2}.rung.declared{background:#fff5e0;border-color:#e8c57e}.table-scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}th{text-align:left;color:var(--muted);font-size:11px;font-weight:600}td,th{padding:10px 8px;border-bottom:1px solid #edf1ef}td:last-child{text-align:right}.status{white-space:nowrap;font-size:11px;color:var(--muted)}.status.ok{color:var(--green)}.status.declared{color:var(--amber)}.callout{background:#f0f7f3;border-left:3px solid #8abbaa;padding:12px 14px;font-size:12px;margin-top:16px}.callout.warn{background:#fff8e8;border-color:#d6b468}.check{display:flex;gap:10px;padding:7px 0;font-size:12px}.check .icon{color:var(--green);min-width:15px}.check.fail .icon{color:#94a19f}.check small{color:var(--muted)}details{border-top:1px solid var(--line);margin-top:16px;padding-top:12px}summary{cursor:pointer;font-size:13px;font-weight:600}.method{font-size:12px;color:var(--muted)}.method li{margin:8px 0}.footer{border-top:1px solid var(--line);margin-top:26px;padding-top:16px;font-size:11px;color:var(--muted)}[hidden]{display:none!important}:focus-visible{outline:3px solid #dd9e30;outline-offset:3px}
.method-picker{margin-top:24px;padding:18px 22px;border:1px solid var(--line);border-radius:14px;background:white}.method-picker label{font-weight:700;margin-right:10px}.method-picker select{font:inherit;color:var(--ink);background:var(--paper);padding:9px;border:1px solid var(--line);border-radius:8px;max-width:100%}[data-method-view=anthropic]{margin:20px 0}.strict-title{font-size:28px;font-weight:750;line-height:1.4}.evidence-table td:last-child{text-align:left}.eval-outcomes{min-width:660px}.eval-outcomes td{white-space:nowrap}.references{margin-top:22px}.references li{margin:12px 0}
@media(max-width:760px){.wrap{padding:22px 16px}.top{align-items:flex-start}h1{font-size:25px}.hero{grid-template-columns:1fr;padding:24px;gap:18px}.hero-right{border-left:0;border-top:1px solid #ffffff26;padding:16px 0 0}.metric-grid{grid-template-columns:repeat(2,1fr)}.metric{padding:16px}.columns{grid-template-columns:1fr}.ladder{grid-template-columns:repeat(4,1fr)}.tabs{width:100%}.tabs button{flex:1;padding:9px}.level{font-size:52px}.level small{display:block;font-size:17px;margin:8px 0}.export{font-size:11px;padding:8px}.card{padding:18px}}
@media print{body{background:white}.wrap{max-width:none;padding:0}.tabs,.export,.method-picker{display:none}.hero{print-color-adjust:exact}.card,.metric{break-inside:avoid}.columns{display:block}.card{margin-bottom:15px}}
"""
SCRIPT = """
{
  const root = document.querySelector('main');
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
    selection = f"{since or 'Any date'} to {until or 'Any date'}" if since or until else 'All logs (no date filter)'
    if report.get('project_filter', {}).get('enabled'):
        selection += ' · Project directory and descendants only'
    start, end = observed.get('since'), observed.get('until')
    coverage = f'{start} to {end}' if start and end else 'No valid timestamps'
    filters = report.get('task_filters', {})
    filter_text = ' · '.join(f'{label}: {e(filters[key])}' for key, label in
                             (('model', 'model'), ('reasoning_effort', 'effort')) if filters.get(key))
    task_note = (f'<p class="muted">Task evidence filter: {filter_text} (does not change the historical L0–L7 level)</p>'
                 if filter_text else '')
    return (f'<div class="card" style="margin-bottom:20px"><strong>Selected period: {e(selection)}</strong>'
            f'<p class="muted">Observed log coverage: {e(coverage)} · UTC (both dates inclusive)</p>'
            f'{task_note}</div>')


def _panel(name, report):
    o, scope = report['observed'], report['scope']
    level = report['current_level']
    title = 'Insufficient data' if level is None else LEVELS[level]
    label = '—' if level is None else f'L{level}'
    declared = report['assessment_basis'] == 'self-reported'
    badge = 'Self-reported evidence · Not independently verified' if declared else ('Waiting for valid samples' if level is None else 'Log behavior candidate · Not a capability certification')
    next_level = report['next_target']
    next_text = 'Collect analyzable log samples' if next_level is None else (
        'Continue auditing and regression evaluations' if next_level == 7 and level == 7 else f'Next · L{next_level} {LEVELS[next_level]}')
    p = [f'<section role="tabpanel" id="panel-{e(name)}" aria-labelledby="tab-{e(name)}" tabindex="0">',
         _period(report), '<div data-method-view="levels">',
         '<div class="hero"><div><div class="eyebrow">ENGINEERING LEVELS / ' + e(LABELS[name]) + '</div>',
         f'<div class="level">{label}<small>{e(title)}</small></div>',
         f'<span class="badge {"declared" if declared else ""}">{badge}</span></div>',
         '<div class="hero-right"><strong>' + e(next_text) + '</strong>',
         f'<p class="muted">{scope["sessions"]:,} sessions · {scope["active_days"]} active days</p>',
         '<p class="muted">Highest observed behavior level: ' + e('Unknown' if report['observed_level'] is None else 'L' + str(report['observed_level'])) + '</p></div></div>']
    visibility = report.get('level_visibility', {})
    if visibility.get('may_undercount_edits_and_verification'):
        p.append('<div class="callout warn">Code orchestration calls ' +
                 e(visibility['opaque_orchestrator_calls']) +
                 ' have no visible nested tool trace. This level reflects visible logs only '
                 'and may undercount edits and verification. See task outcome assessment '
                 'for Codex acceptance results.</div>')
    p.extend(['<div class="metric-grid">',
              _metric('Human inputs', _number(o['humanish_user']), 'Excludes system and subagent input'),
              _metric('Tool calls', _number(o['tool_calls']), f"{o['tool_per_human']:.2f} calls / human input"),
              _metric('Edit → verify sessions', _number(o['engineering_sessions']), 'Edit then build / test in the same session'),
              _metric('Verification attempt share', f"{o['verification_ratio']:.1%}", 'build + test / shell calls'),
              '</div>',
              '<div class="card"><h2>Level ladder</h2><p class="muted">L3–L4 show behavior signals; L5–L7 show self-reported capability evidence. L7 is an optional research direction.</p><div class="ladder">'])
    for i, text in enumerate(LEVELS):
        cls = ('declared' if declared else 'current') if level == i else ''
        p.append(f'<div class="rung {cls}"><b>L{i}</b>{e(text)}</div>')
    p.append('</div></div><div class="columns"><div class="card"><h2>Level requirements and gaps</h2>')
    for key, gate in report['levels'].items():
        status = gate['status']
        status_text = {'OBSERVED': 'Behavior observed', 'DECLARED': 'Self-reported evidence met', 'NOT VERIFIED': 'Unmet / Earlier level unmet'}[status]
        p.append(f'<details {"open" if key == "L" + str(next_level) else ""}><summary>{e(key)} · <span class="status {"ok" if status == "OBSERVED" else "declared" if status == "DECLARED" else ""}">{status_text}</span></summary>')
        for check in gate['checks']:
            p.append(f'<div class="check {"" if check["pass"] else "fail"}"><span class="icon">{"✓" if check["pass"] else "○"}</span><div>{e(check["check"])}<br><small>{e(check["detail"])}</small></div></div>')
        p.append('</details>')
    if report.get('note'):
        p.append('<div class="callout">' + e(report['note']) + '</div>')
    p.append('</div><div class="card"><h2>Data coverage and quality</h2>')
    p.append(f'<p>{scope["files_with_data"]} / {scope["files_scanned"]} files contain in-window data</p><p>JSON parse errors: {scope["parse_errors"]}</p>')
    for key, value in scope['diagnostics'].items():
        p.append(f'<p class="method">{e(DIAGNOSTICS.get(key, key))}: {value}</p>')
    p.append('</div></div><div class="card method"><h2>How to read this report</h2><ul>')
    for note in report['limitations']:
        p.append('<li>' + e(note) + '</li>')
    p.append('<li>Thresholds set a sample floor and have not been calibrated across teams; sessions are not completed tasks.</li><li>Only aggregate counts are shown. Prompts, code, raw commands, and tool arguments are omitted.</li></ul></div></div>')
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
        return '<div data-method-view="anthropic" class="card">Anthropic evaluation data is missing.</div>'
    c, k = r['counts'], r['k']
    local = r['evidence_basis'] == 'local_checked'
    activity = r.get('historical_activity', {})
    history = ''
    if activity.get('sessions'):
        history = ('<div class="card" style="margin-bottom:20px"><h2>Historical activity · Completion signals</h2>'
                   '<div class="metric-grid">' +
                   _metric('Primary sessions', activity['sessions'], 'Log sessions, not task count') +
                   _metric('Latest turn ended', activity['ended_sessions'], 'Explicit end marker present') +
                   _metric('Interrupted or errored', activity['interrupted_sessions'], 'Latest state is interrupted or errored') +
                   _metric('No end marker', activity['open_sessions'], 'May be active or incomplete logs') +
                   '</div><p>Recognized verification calls ' + e(activity['verification_calls']) +
                   ': successful returns ' + e(activity['verification_passed']) +
                   ' / failed returns ' + e(activity['verification_failed']) +
                   ' / unknown results ' + e(activity['verification_unknown']) + '</p>' +
                   '<p class="method">' + e(HISTORY_NOTE) + '</p></div>')
    if activity.get('opaque_orchestrator_calls'):
        history += ('<div class="callout warn">Unexpanded orchestration calls ' +
                    e(activity['opaque_orchestrator_calls']) +
                    '; internal verification is excluded from these counts. Zero recognized calls does not imply no verification.</div>')
    p = ['<div data-method-view="anthropic">' + history + '<div class="hero"><div>',
         '<div class="eyebrow">ANTHROPIC EVAL METHODOLOGY</div>',
         '<div class="strict-title">' + e(r['status_label']) + '</div>',
         '<span class="badge declared">Task outcome assessment · No L0–L7 level</span></div>',
         '<div class="hero-right"><strong>Daily acceptance and controlled evaluations are reported separately</strong>',
         '<p class="muted">Success, failure, unknown, and unrun outcomes retain the full denominator.</p>',
         '<p class="muted">' + ('Local evidence checked · Not an independent audit' if local else 'Historical logs only · No separate task acceptance' if r['evidence_basis'] == 'logs_only' else 'Imported results unchecked · Record completeness only') + '</p></div></div>',
         '<div class="metric-grid">',
         _metric('Tasks', c['tasks'], f"Complete records: {c['complete_tasks']}"),
         _metric('Planned trials', c['expected_trials'], f"Recorded in window: {c['trials']}"),
         _metric('Trials with grader evidence', c['graded_trials'], 'Planned graders agree with outcome'),
         _metric('Local evidence verification', c['verified_trials'], 'Checks hashes, grader content, and artifact links' if local else 'Local verification disabled'),
         '</div><div class="metric-grid">',
         _metric('Success', c['successful_trials'], 'All required graders passed'),
         _metric('Failure', c['failed_trials'], 'Explicit acceptance failure'),
         _metric('Unknown', c['unknown_trials'], f"Out-of-window trials included: {c['outside_window_trials']}"),
         _metric('Unrun / Not supplied', c['not_run_trials'], 'No trial record for planned run'), '</div>']
    if c.get('collector_journal_trials') or c.get('session_export_trials'):
        p.append('<div class="callout">Trace coverage: collector journal ' + e(c.get('collector_journal_trials', 0)) +
                 ' runs / session export ' + e(c.get('session_export_trials', 0)) +
                 ' runs. The event journal covers registration, notes, and acceptance, not the full session transcript.</div>')
    if r.get('synthetic'):
        p.append('<div class="callout warn">Synthetic example data illustrates the format and statistics; it does not represent real capability.</div>')
    if r['evidence_basis'] == 'logs_only':
        p.append('<div class="callout warn">Only activity logs are available, without task acceptance outcomes. This does not mean failure or zero capability. Register tasks and acceptance criteria before collecting results; historical sessions are not treated as independent trials.</div>')
    window = r['trial_window']
    coverage = f"{window['since']} to {window['until']}" if window['since'] else 'No valid trial dates'
    p.append('<p class="method">Evaluation trial coverage: ' + e(coverage) + ' · UTC</p>')
    for mode, title in (('daily', 'Daily task acceptance'), ('controlled', 'Controlled repeat evaluation')):
        rows = [g for g in r['groups'] if g['evaluation_mode'] == mode]
        p.append('<div class="card" style="margin-top:18px"><h2>' + title + '</h2>')
        if not rows:
            p.append('<p class="muted">No results for this mode yet.</p>')
        for g in rows:
            o = g['outcomes']
            p.append('<h3>' + e(g['label']) + ' · ' + e(LABELS[g['source']]) + '</h3>')
            p.append(f'<p class="method">Tasks {g["tasks"]} · Complete tasks {g["complete_tasks"]} · Success {o["success"]} / failure {o["failure"]} / unknown {o["unknown"]} / unrun {o["not_run"]}</p>')
            p.append('<div class="table-scroll"><table class="eval-outcomes"><thead><tr><th>Grading coverage</th><th>Graded pass rate</th><th>Planned success bounds</th>')
            if mode == 'daily':
                p.append('<th>Complete task acceptance rate</th><th>95% Wilson interval</th></tr></thead><tbody><tr>')
                tail = '<td>' + _percent(g['daily_success_rate']) + '</td><td>' + _interval(g['daily_wilson_95']) + '</td>'
            else:
                p.append(f'<th>pass@1</th><th>pass@{k}</th><th>pass^{k}</th></tr></thead><tbody><tr>')
                tail = ''.join('<td>' + _percent(g[key]) + '</td>' for key in ('pass_at_1', 'pass_at_k', 'pass_power_k'))
            p.append('<td>' + _percent(g['coverage']) + '</td><td>' + _percent(g['observed_success_rate']) +
                     '</td><td>' + _interval(g['success_bounds']) + '</td>' + tail + '</tr></tbody></table></div>')
            duration, human = g['duration_seconds'], g['human_interventions']
            elapsed = f"{duration['total']:.1f} sec / {duration['recorded']} records" if duration['recorded'] else 'Not recorded'
            interventions = f"{human['total']:g} times / {human['recorded']} records" if human['recorded'] else 'Not recorded'
            p.append('<p class="method">Locally verified evidence: ' + str(o['verified']) + ' runs · Duration: ' + elapsed + ' · Human interventions: ' + interventions + '</p>')
        if mode == 'daily':
            p.append('<p class="method">Daily tasks have one acceptance run and require neither environment reset nor a reference solution. Repeat reliability is not calculated. Wilson intervals require complete groups and an approximately independent, identically distributed sample.</p>')
        else:
            p.append(f'<p class="method">pass@{k}: at least one success in {k} runs; pass^{k}: success in all {k} runs. Calculated only for complete controlled task groups with enough repeats; trials from different sources, models, harnesses, or versions are not pooled.</p>')
        p.append('</div>')
    p.append('<div class="callout warn">The graded pass rate covers only trials with results and may have selection bias. Bounds treat unknown and unrun trials as failures or successes, with equal task weights. This is a missing-data range, not a confidence interval. — means unavailable, not 0%.</div>')
    if r['failure_reasons']:
        p.append('<div class="card" style="margin-top:18px"><h2>Failure and missing evidence reasons</h2>')
        for reason, n in r['failure_reasons'].items():
            p.append('<p>' + e(REASONS.get(reason, reason)) + ': ' + str(n) + '</p>')
        p.append('</div>')
    p.append('<div class="card" style="margin-top:18px"><h2>Method requirements and evidence coverage</h2><div class="table-scroll"><table class="evidence-table"><thead><tr><th>Evaluation step</th><th>Recorded / Expected</th><th>Required evidence</th></tr></thead><tbody>')
    for row in r['readiness']:
        coverage = f"{row['present']} / {row['total']}" if row['total'] else 'Not applicable / Not supplied'
        p.append('<tr><td>' + e(row['label']) + '</td><td>' + coverage + '</td><td>' + e(row['requirement']) + '</td></tr>')
    p.append('</tbody></table></div><p class="method">Field coverage and local evidence verification are counted separately. A reference does not prove sufficient requirement coverage. Human review is shown separately.</p></div>')
    if r['diagnostics']:
        p.append('<div class="callout warn">Imported data diagnostics: ' + e(json.dumps(r['diagnostics'], ensure_ascii=False)) + '. Conflicting or anomalous records are isolated; invalid unassigned tasks are excluded from group denominators.</div>')
    p.append('<details class="card method"><summary>Scoring rules, limitations, and method source</summary><ul>')
    p.extend('<li>' + e(note) + '</li>' for note in r['limitations'])
    p.append('</ul><a href="' + e(r['reference_url']) + '">Read Anthropic’s published evaluation method ↗</a></details></div>')
    return ''.join(p)


def _improvement_panel(report):
    r = report.get('self_improvement_evaluation')
    if r is None:
        return '<div data-method-view="improvement" class="card">Self-improvement comparison data is missing.</div>'
    p = ['<div data-method-view="improvement"><div class="card"><h2>Local self-improvement comparison</h2>',
         '<p class="method">Compare autonomous acceptance before and after a change on fixed tasks and graders. '
         'This view does not promote L6 or certify independent execution.</p>']
    if not r['comparisons']:
        p.append('<div class="callout warn">No predefined controlled before/after comparison is available. L6 self-reports do not prove improvement.</div>')
    for row in r['comparisons']:
        p.append('<h3>' + e(row['label']) + ' · ' + e(LABELS.get(row['source'], row['source'])) + '</h3>')
        p.append('<p>Status: ' + e(row['status']) + '</p>')
        if row['reason']:
            p.append('<p class="method">Evidence gap: ' + e(row['reason']) + '</p>')
            continue
        p.append('<p>Tasks ' + e(row['tasks']) + ' · Trials per version ' + e(row['trials_per_variant']) +
                 ' · Autonomous success rate ' + _percent(row['baseline_autonomous']) + ' → ' +
                 _percent(row['candidate_autonomous']) + ' (' + e(f"{row['autonomous_delta']:+.1%}") + ')</p>')
        p.append('<p class="method">Overall success rate ' + _percent(row['baseline_success']) + ' → ' +
                 _percent(row['candidate_success']) + ' · Improved / regressed / unchanged tasks ' +
                 e(f"{row['improved_tasks']}/{row['regressed_tasks']}/{row['unchanged_tasks']}") +
                 ' · Sign test p=' + e(row['sign_test_p'] if row['sign_test_p'] is not None else 'N/A') + '</p>')
    p.append('<div class="callout warn">Local checks are not independent execution. An outside evaluator must control the task suite, runs, and evidence.</div>')
    p.append('<details class="method"><summary>Interpretation limits</summary><ul>')
    p.extend('<li>' + e(note) + '</li>' for note in r['limitations'])
    p.append('</ul></details></div></div>')
    return ''.join(p)


def _references():
    return (f'<details class="card references method"><summary>Research and official references · {len(REFERENCES)} items</summary>'
            '<p>' + e(METHOD_NOTE) + '</p><ul>' + ''.join(
                '<li><a href="' + e(ref['url']) + '">' + e(ref['title']) + '</a> · ' +
                e(ref['publisher']) + '<br>' + e(ref['scope']) + '</li>' for ref in REFERENCES) + '</ul></details>')


def render_html(bundle, default_method='both'):
    reports = bundle['reports']
    report_name = bundle.get('report_name', 'AI Engineering Assessment')
    report_file_stem = bundle.get('report_file_stem', 'ai-engineering-assessment')
    method_options = ''.join(
        '<option value="' + value + '"' + (' selected' if value == default_method else '') + '>' + label + '</option>'
        for value, label in (('levels', 'Engineering levels L0–L7 · Heuristic model'),
                             ('anthropic', 'Anthropic method · Evidence based'),
                             ('improvement', 'Self-improvement · Before and after'), ('both', 'Show all views')))
    payload = base64.b64encode(json.dumps(bundle, ensure_ascii=False, indent=2).encode()).decode()
    generated = next(iter(reports.values()))['generated_at'] if reports else ''
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             '<title>' + e(report_name) + '</title>',
             '<style>' + CSS + '</style></head><body><main class="wrap">',
             '<header class="top"><div><div class="eyebrow">LOCAL INSIGHTS / THREE VIEWS</div><h1>' + e(report_name) + '</h1>',
             '<p class="muted">Review engineering levels, task outcomes, and improvement comparisons together.</p></div>',
             f'<a class="export" download="{e(report_file_stem)}.json" href="data:application/json;base64,{payload}">Export JSON ↗</a></header>',
             '<div class="method-picker"><label for="assessment-method">Assessment method</label> '
             '<select id="assessment-method">' + method_options + '</select>'
             '<p class="method">' + e(METHOD_NOTE) + '</p></div>',
             '<nav class="tabs" role="tablist" aria-label="Data source">']
    for i, name in enumerate(reports):
        parts.append(f'<button role="tab" id="tab-{e(name)}" aria-controls="panel-{e(name)}" data-panel="panel-{e(name)}" aria-selected="{str(i == 0).lower()}">{e(LABELS[name])}</button>')
    parts.append('</nav><noscript><p>JavaScript is disabled; all sources and three assessment views follow.</p></noscript>')
    parts.extend(_panel(name, report) for name, report in reports.items())
    parts.append(_references())
    parts.append('<footer class="footer">' + e(bundle['merge_note']) + '<br>Offline report · No external resources or data upload · Ruleset ' + e(bundle['ruleset_version']) + ' · ' + e(generated) + '</footer>')
    parts.append('</main><script>' + SCRIPT + '</script></body></html>')
    return ''.join(parts)
