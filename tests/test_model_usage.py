"""Model attribution, token reconciliation and offline usage report regressions."""
import shutil

import assess as A
import assessment.logs as L
from tests.test_level_assessment import assistant
from tests.test_assessment_core import TempCase, record, tokens


def context(model, turn='t1', ts='2026-09-10T10:00:00Z'):
    return record('turn_context', {'model': model, 'turn_id': turn}, ts)


def usage(response, turn='t1', n=100, out=20, ts='2026-09-10T10:00:00Z', **extra):
    return record('token_usage_record', {'response_id': response, 'turn_id': turn,
                  'usage': dict(input_tokens=n, cached_input_tokens=30,
                                cache_write_input_tokens=5, output_tokens=out,
                                reasoning_output_tokens=7, **extra)}, ts)


class TestModelUsage(TempCase):
    def report(self, m, since=None, until=None):
        return A.build_report(m, A.evaluate(m), since, until)

    def assert_reconciles(self, m):
        data = L.usage_breakdown(m)
        for field in L.USAGE_FIELDS:
            self.assertEqual(sum(r[field] for r in data['models']), getattr(m, field), field)
            self.assertEqual(sum(r[field] for r in data['daily']), getattr(m, field), field)
        self.assertEqual(sum(r['total_tokens'] for r in data['models']), m.input_tokens + m.output_tokens)
        return data

    def test_claude_split_messages_and_duplicate_records(self):
        first = assistant(cache_read=30, cache_creation=5, out=10)
        first['message']['id'] = 'msg-1'
        first['uuid'] = 'block-1'
        second = assistant(cache_read=30, cache_creation=5, out=20)
        second['message']['id'] = 'msg-1'
        second['uuid'] = 'block-2'
        third = assistant(out=5, ts='2026-09-11T10:00:00Z')
        third['message']['model'] = 'claude-sonnet-test'
        self.write('projects/a.jsonl', [first, second, second, third])
        m = L.scan(self.root)
        self.assertEqual((m.input_tokens, m.output_tokens), (37, 25))
        data = self.assert_reconciles(m)
        self.assertEqual({r['model'] for r in data['models']}, {'claude-opus-5', 'claude-sonnet-test'})
        self.assertEqual(len(data['daily']), 2)
        self.assertTrue(all(r['reasoning_records'] == 0 for r in data['models']))

    def test_codex_delayed_usage_follows_turn_model_and_deduplicates_archive(self):
        records = [context('model-a', 'a'), context('model-b', 'b'),
                   usage('r1', 'a'), usage('r2', 'b', n=200), usage('r1', 'a'),
                   tokens(9000)]
        path = self.codex(records)
        (self.root / 'archived_sessions').mkdir()
        shutil.copy(path, self.root / 'archived_sessions/copy.jsonl')
        m = L.scan_codex(self.root)
        data = self.assert_reconciles(m)
        self.assertEqual({r['model']: r['total_tokens'] for r in data['models']},
                         {'model-a': 120, 'model-b': 220})
        self.assertEqual((m.input_tokens, m.output_tokens, m.reasoning_output_tokens), (300, 40, 14))

    def test_codex_cumulative_baseline_before_window_and_model_switch(self):
        self.codex([context('model-a'), tokens(100, 30, 10, '2026-09-09T10:00:00Z'),
                    tokens(140, 40, 20), context('model-b'), tokens(170, 45, 25),
                    tokens(170, 45, 25)])
        m = L.scan_codex(self.root, since=L.parse_date('2026-09-10'))
        data = self.assert_reconciles(m)
        self.assertEqual({r['model']: r['total_tokens'] for r in data['models']},
                         {'model-a': 50, 'model-b': 35})

    def test_model_context_before_window_and_explicit_model(self):
        explicit = usage('r2')
        explicit['payload']['model'] = 'explicit-model'
        self.codex([context('context-model', ts='2026-09-09T10:00:00Z'), usage('r1'), explicit])
        m = L.scan_codex(self.root, since=L.parse_date('2026-09-10'))
        self.assertEqual({r['model'] for r in self.assert_reconciles(m)['models']},
                         {'context-model', 'explicit-model'})

    def test_unknown_turn_is_not_attributed_to_current_model(self):
        self.codex([context('model-a'), usage('r1', turn='missing')])
        data = self.assert_reconciles(L.scan_codex(self.root))
        self.assertEqual(data['models'][0]['model'], 'unknown')

    def test_undated_usage_in_totals_but_not_daily_series(self):
        self.codex([usage('r1', ts='invalid')])
        m = L.scan_codex(self.root)
        data = L.usage_breakdown(m)
        self.assertEqual(data['models'][0]['total_tokens'], 120)
        self.assertEqual(data['daily'], [])
        self.assertEqual(L.scan_codex(self.root, since=L.parse_date('2026-09-01')).input_tokens, 0)

    def test_merge_keeps_same_model_names_separate_by_source(self):
        rec = assistant(out=3)
        rec['message']['model'] = 'same-name'
        self.write('projects/a.jsonl', [rec])
        self.codex([context('same-name'), usage('r1')])
        m = L.merge_metrics([L.scan(self.root), L.scan_codex(self.root)])
        data = self.assert_reconciles(m)
        self.assertEqual(len(data['models']), 2)
        self.assertEqual({r['source'] for r in data['models']}, {'claude', 'codex'})

    def test_optional_reasoning_field_does_not_reset_cumulative_input(self):
        first = tokens(100, 30, 10)
        first['payload']['info']['total_token_usage']['reasoning_output_tokens'] = 5
        last = tokens(140, 40, 20)
        last['payload']['info']['total_token_usage']['reasoning_output_tokens'] = 8
        self.codex([context('model-a'), first, tokens(120, 35, 15), last])
        m = L.scan_codex(self.root)
        self.assertEqual((m.input_tokens, m.output_tokens, m.reasoning_output_tokens), (140, 20, 8))
        self.assert_reconciles(m)

    def test_counter_reset_does_not_recount_previous_reasoning(self):
        first = tokens(100, 30, 10)
        first['payload']['info']['total_token_usage']['reasoning_output_tokens'] = 5
        last = tokens(30, 10, 8)
        last['payload']['info']['total_token_usage']['reasoning_output_tokens'] = 2
        self.codex([context('model-a'), first, tokens(20, 5, 4), last])
        m = L.scan_codex(self.root)
        self.assertEqual((m.input_tokens, m.output_tokens, m.reasoning_output_tokens), (130, 18, 7))
        self.assert_reconciles(m)

    def test_daily_dates_are_utc(self):
        self.codex([context('model-a'), usage('r1', ts='2026-09-11T01:00:00+08:00')])
        self.assertEqual(self.assert_reconciles(L.scan_codex(self.root))['daily'][0]['date'], '2026-09-10')


class TestUsageReport(TempCase):
    def report(self):
        self.codex([context('model-a'), usage('r1'),
                    usage('r2', ts='2026-09-17T10:00:00Z'),
                    usage('r3', ts='invalid')])
        m = L.scan_codex(self.root)
        return A.build_report(m, A.evaluate(m), None, None)

    def test_period_boundaries_exclude_undated_and_honor_report_end(self):
        from assessment.web_usage import period_data
        report = self.report()
        all_rows, _, end = period_data(report)
        self.assertEqual(sum(r['total_tokens'] for r in all_rows), 360)
        self.assertEqual(end.isoformat(), '2026-09-17')
        rows, daily, _ = period_data(report, 7)
        self.assertEqual(sum(r['total_tokens'] for r in rows), 120)
        self.assertEqual([r['date'] for r in daily], ['2026-09-17'])
        self.assertEqual(sum(r['total_tokens'] for r in period_data(report, 8)[0]), 240)
        self.assertEqual(sum(r['total_tokens'] for r in period_data(report, 30)[0]), 240)
        report['requested_window'] = {'until': '2026-10-01'}
        self.assertEqual(period_data(report, 7)[0], [])

    def test_render_counts_shares_sources_and_escaping(self):
        from assessment.web_usage import render_usage
        report = self.report()
        # Input includes cache: 300 - 90 read - 15 write = 195 uncached.
        html = render_usage('codex', report)
        self.assertIn('In: 195 · Out: 60', html)
        self.assertIn('Cache: 90 read · 15 write', html)
        self.assertIn('(100.0%)', html)
        self.assertIn('每日 Token 用量', html)
        row = report['model_usage']['models'][0]
        row['model'] = '<script>"model"</script>'
        report['model_usage']['models'].append(dict(row, source='claude'))
        html = render_usage('combined', report)
        self.assertIn('(50.0%)', html)
        self.assertIn('Claude Code', html)
        self.assertIn('Codex', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('<script>', html)

    def test_missing_zero_and_single_day_usage(self):
        from assessment.web_usage import render_usage
        self.assertIn('No model token usage', render_usage('codex', {}))
        report = self.report()
        usage_data = report['model_usage']
        usage_data['daily'] = usage_data['daily'][:1]
        for row in usage_data['models'] + usage_data['daily']:
            for key in L.USAGE_FIELDS + ('total_tokens',):
                row[key] = 0
        html = render_usage('codex', report)
        self.assertIn('(0.0%)', html)
        self.assertIn('<circle', html)
        self.assertNotIn('nan', html.lower())

    def test_usage_is_in_metrics_area_with_unique_period_targets(self):
        import re
        from assessment.web import render_html
        report = self.report()
        html = render_html({'reports': dict.fromkeys(('claude', 'codex', 'combined'), report),
                            'merge_note': 'test', 'ruleset_version': '1.0'})
        self.assertLess(html.index('Human inputs'), html.index('<section class="model-usage">'))
        self.assertLess(html.index('<section class="model-usage">'), html.index('class="card level-explorer"'))
        ids = re.findall(r'\bid="([^"]+)"', html)
        self.assertEqual(len(ids), len(set(ids)))
        targets = re.findall(r'aria-controls="(usage-[^"]+)"', html)
        self.assertEqual(len(targets), 9)
        self.assertTrue(set(targets).issubset(ids))
        self.assertEqual(html.count('data-usage-period="all" aria-pressed="true"'), 3)
        self.assertIn('id="usage-codex-7" hidden', html)
        self.assertIn("section.querySelector('#' + item.getAttribute('aria-controls')).hidden = !active", html)
