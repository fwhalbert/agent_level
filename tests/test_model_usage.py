"""Model attribution, token reconciliation and offline usage report regressions."""
import json
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
        return json.loads(A.render_json(m, A.evaluate(m, {}), since, until, None))

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
