"""Offline model token usage charts and summaries from aggregate report data."""
from collections import Counter, defaultdict
from datetime import date, timedelta
from html import escape

from .web_i18n import attributes, text as t

COLORS = ('#7565c5', '#20916c', '#bd8500', '#2979bc', '#c45b78', '#698135')
ROLES = {'executor': 'Execution', 'auto_review': 'Automatic approval review',
         'subagent': 'Subagent', 'unknown': 'Unknown role'}
TOKEN_FIELDS = ('input_tokens', 'output_tokens', 'cache_read', 'cache_creation',
                'total_tokens', 'uncached_input_tokens')
CSS = """
.model-usage{border-bottom:1px solid var(--line);padding:0 0 24px;margin:0 0 28px}
.usage-header{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:12px}.usage-header h2{margin:0}
.usage-periods{display:flex;gap:6px;flex-wrap:wrap}.usage-periods button{border:0;background:transparent;color:var(--muted);padding:6px 10px;border-radius:4px;font-size:13px}.usage-periods button[aria-pressed=true]{background:#eef2f8;color:var(--accent);font-weight:650}
.usage-chart{display:block;width:100%;height:auto;max-height:290px;overflow:visible}.usage-chart text{font:12px system-ui,sans-serif;fill:var(--muted)}.usage-chart .grid{stroke:var(--line);stroke-width:1}.usage-line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.usage-models{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px 32px;margin-top:20px}.usage-model{min-width:0;font-variant-numeric:tabular-nums}.usage-model h3{margin:0;font-size:15px;overflow-wrap:anywhere}.usage-dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px;background:var(--model-color)}.usage-share{font-weight:400;color:var(--muted);margin-left:8px}.usage-model p{margin:2px 0 0 18px;font-size:13px;color:var(--muted)}
.usage-total{font-weight:600;font-variant-numeric:tabular-nums}.usage-role-table{min-width:740px}.usage-role-table td:not(:first-child),.usage-role-table th:not(:first-child){text-align:right}.usage-role-table tfoot{font-weight:600}.usage-role-table th{white-space:nowrap}
@media(max-width:760px){.usage-models{grid-template-columns:1fr}.usage-chart text{font-size:28px}}
"""
SCRIPT = """
  root.querySelectorAll('.model-usage').forEach(section => {
    const buttons = [...section.querySelectorAll('[data-usage-period]')];
    buttons.forEach(button => button.addEventListener('click', () => {
      buttons.forEach(item => {
        const active = item === button;
        item.setAttribute('aria-pressed', String(active));
        section.querySelector('#' + item.getAttribute('aria-controls')).hidden = !active;
      });
    }));
  });
"""


def compact(value):
    for divisor, suffix in ((1_000_000_000, 'b'), (1_000_000, 'm'), (1_000, 'k')):
        if value >= divisor:
            return f'{value / divisor:.1f}{suffix}'
    return str(value)


def _period_data(report, days=None, *, roles=False):
    usage = report.get('model_usage', {})
    rows = usage.get('roles' if roles else 'models', [])
    daily = usage.get('daily_roles' if roles else 'daily', [])
    identity = 'role' if roles else 'model'
    # Older reports have no role metadata; keep their tokens explicitly unknown.
    if roles and 'roles' not in usage:
        rows = [dict(row, role='unknown') for row in usage.get('models', [])]
        daily = [dict(row, role='unknown') for row in usage.get('daily', [])]
    end = (report.get('requested_window', {}).get('until') or
           report.get('observed_window', {}).get('until') or
           max((row['date'] for row in daily), default=None))
    end = date.fromisoformat(end[:10]) if end else None
    if days is None:
        return rows, daily, end
    if end is None:
        return [], [], end
    start = (end - timedelta(days=days - 1)).isoformat()
    daily = [row for row in daily if start <= row['date'] <= end.isoformat()]
    totals = defaultdict(Counter)
    for row in daily:
        totals[row['source'], row[identity]].update({key: row.get(key, 0) for key in TOKEN_FIELDS})
    return [dict(counts, source=key[0], **{identity: key[1]})
            for key, counts in totals.items()], daily, end


def period_data(report, days=None):
    return _period_data(report, days)


def role_period_data(report, days=None):
    return _period_data(report, days, roles=True)


def _uncached(row):
    return max(0, row.get('input_tokens', 0) - row.get('cache_read', 0) - row.get('cache_creation', 0))


def _role_table(rows):
    if not rows:
        return ''
    totals = Counter()
    by_role = defaultdict(Counter)
    for row in rows:
        role = row.get('role') if row.get('role') in ROLES else 'unknown'
        counts = {key: row.get(key, 0) for key in TOKEN_FIELDS}
        counts['uncached_input_tokens'] = _uncached(row)
        totals.update(counts)
        by_role[role].update(counts)
    headers = ('Role', 'Total tokens', 'Share', 'Uncached input', 'Cache read', 'Cache write', 'Output')
    parts = ['<h3>' + t('Token usage by role') + '</h3><div class="table-scroll">'
             '<table class="usage-role-table"><thead><tr>' +
             ''.join('<th scope="col">' + t(label) + '</th>' for label in headers) + '</tr></thead><tbody>']
    for role in ROLES:
        if role not in by_role:
            continue
        row = by_role[role]
        share = row['total_tokens'] / totals['total_tokens'] if totals['total_tokens'] else 0
        parts.append('<tr><th scope="row">' + t(ROLES[role]) + '</th><td>' + compact(row['total_tokens']) +
                     f'</td><td>{share:.1%}</td>' + ''.join('<td>' + compact(row[key]) + '</td>'
                     for key in ('uncached_input_tokens', 'cache_read', 'cache_creation', 'output_tokens')) + '</tr>')
    parts.append('</tbody><tfoot><tr><th scope="row">' + t('All roles') + '</th><td>' +
                 compact(totals['total_tokens']) + '</td><td>—</td>' +
                 ''.join('<td>' + compact(totals[key]) + '</td>' for key in
                         ('uncached_input_tokens', 'cache_read', 'cache_creation', 'output_tokens')) +
                 '</tr></tfoot></table></div>')
    return ''.join(parts)


def _chart(daily, colors, end, days):
    if not daily:
        return '<p class="method">' + t('No dated token usage in this period.') + '</p>'
    by_model = defaultdict(Counter)
    for row in daily:
        by_model[row['source'], row['model']][row['date']] += row['total_tokens']
    first = date.fromisoformat(min(row['date'] for row in daily))
    last = date.fromisoformat(max(row['date'] for row in daily))
    if days and end:
        first, last = end - timedelta(days=days - 1), end
    span = (last - first).days
    dates = [(first + timedelta(days=i)).isoformat() for i in range(span + 1)]
    peak = max((max(counts.values()) for counts in by_model.values()), default=0) or 1
    x = lambda i: 70 + (i / span * 900 if span else 450)
    y = lambda value: 210 - value / peak * 180
    parts = ['<svg class="usage-chart" viewBox="0 0 1000 245" role="img" ' +
             attributes('Tokens per day').replace('data-en=', 'data-aria-en=').replace('data-zh=', 'data-aria-zh=') +
             ' aria-label="Tokens per day">']
    for i in range(5):
        value = peak * i / 4
        parts.append(f'<line class="grid" x1="70" x2="970" y1="{y(value):.1f}" y2="{y(value):.1f}"/>'
                     f'<text x="60" y="{y(value) + 4:.1f}" text-anchor="end">{compact(round(value))}</text>')
    for i in sorted({0, span // 3, span * 2 // 3, span}):
        anchor = 'middle' if not span else 'start' if i == 0 else 'end' if i == span else 'middle'
        parts.append(f'<text x="{x(i):.1f}" y="238" text-anchor="{anchor}">{dates[i]}</text>')
    for key, counts in sorted(by_model.items()):
        points = ' '.join(f'{x(i):.1f},{y(counts[day]):.1f}' for i, day in enumerate(dates))
        color = colors[key]
        parts.append(f'<polyline class="usage-line" stroke="{color}" points="{points}"><title>{escape(key[1])}</title></polyline>')
        if span == 0:
            parts.append(f'<circle cx="{x(0):.1f}" cy="{y(counts[dates[0]]):.1f}" r="3" fill="{color}"/>')
    return ''.join(parts) + '</svg>'


def render_usage(name, report):
    usage = report.get('model_usage', {})
    keys = sorted({(row['source'], row['model']) for row in usage.get('models', []) + usage.get('daily', [])})
    colors = {key: COLORS[i % len(COLORS)] for i, key in enumerate(keys)}
    periods = (('all', None, 'All time'), ('7', 7, 'Last 7 days'), ('30', 30, 'Last 30 days'))
    parts = ['<section class="model-usage"><div class="usage-header"><h2>' + t('Tokens per day') +
             '</h2><div class="usage-periods" role="group" aria-label="Usage period" data-aria-en="Usage period" data-aria-zh="用量时间范围">']
    for period, _, label in periods:
        parts.append(f'<button type="button" data-usage-period="{period}" aria-pressed="{str(period == "all").lower()}" aria-controls="usage-{escape(name, quote=True)}-{period}">{t(label)}</button>')
    parts.append('</div></div>')
    for period, days, _ in periods:
        rows, daily, end = period_data(report, days)
        parts.append(f'<div id="usage-{escape(name, quote=True)}-{period}"' + (' hidden' if days else '') + '>')
        parts.append(_chart(daily, colors, end, days))
        total = sum(row['total_tokens'] for row in rows)
        if rows:
            output = sum(row.get('output_tokens', 0) for row in rows)
            uncached = sum(_uncached(row) for row in rows)
            parts.append('<p class="usage-total">' + t('Total tokens: {total} · Total / output: {ratio} · Uncached input / output: {uncached_ratio}',
                         total=compact(total), ratio=f'{total / output:.1f}' if output else '—',
                         uncached_ratio=f'{uncached / output:.1f}' if output else '—') + '</p>')
            parts.append(_role_table(role_period_data(report, days)[0]))
            parts.append('<h3>' + t('Token usage by model') + '</h3>')
            parts.append('<div class="usage-models">')
            for row in sorted(rows, key=lambda row: (-row['total_tokens'], row['source'], row['model'])):
                share = row['total_tokens'] / total if total else 0
                uncached = _uncached(row)
                parts.append(f'<article class="usage-model" style="--model-color:{colors[row["source"], row["model"]]}"><h3><span class="usage-dot" aria-hidden="true"></span>{escape(row["model"])}<span class="usage-share">({share:.1%})</span></h3>')
                if name == 'combined':
                    parts.append('<p>' + escape({'claude': 'Claude Code', 'codex': 'Codex'}.get(row['source'], row['source'])) + '</p>')
                parts.append('<p>' + t('In: {input} · Out: {output}', input=compact(uncached), output=compact(row['output_tokens'])) + '</p>')
                parts.append('<p>' + t('Cache: {read} read · {write} write', read=compact(row['cache_read']), write=compact(row['cache_creation'])) + '</p></article>')
            parts.append('</div>')
        else:
            parts.append('<p class="method">' + t('No model token usage in this period.') + '</p>')
        parts.append('</div>')
    parts.append('<p class="method">' + t('In excludes cache tokens. Shares and chart include input, cache, and output tokens. Unreported usage is not estimated.') + '</p>')
    parts.append('<p class="method">' + t('Roles come from recorded session metadata. Unknown roles stay unknown. Automatic approval review does not establish independent task acceptance.') + '</p>')
    parts.append('<p class="method">' + t('Token counts are not monetary cost; no pricing is estimated. Ratios describe usage, not productivity.') + '</p>')
    if name == 'combined':
        parts.append('<p class="method">' + t('Combined usage retains all sources and roles. Compare execution, review, and subagent work separately; different logging coverage can affect comparisons.') + '</p>')
    _, _, end = period_data(report)
    if end:
        parts.append('<p class="method">' + t('Within the report filters; recent periods end on {date} (UTC). Undated usage appears only in all-time totals.', date=end.isoformat()) + '</p>')
    return ''.join(parts) + '</section>'
