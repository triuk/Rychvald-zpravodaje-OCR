"""Accounting contracts through public GUI operations and process artifacts."""
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.service import Application


def counters(i=100, c=20, w=10, o=50, r=30):
    return dict(inputTokens=i, cachedInputTokens=c, cacheWriteInputTokens=w,
                outputTokens=o, reasoningOutputTokens=r, totalTokens=i + o)


class MetricsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='OCR metrics ')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.registry = self.directory / 'registry'
        self.app = Application(self.registry)
        self.addCleanup(lambda: self.app.close())
        source = self.directory / 'source.pdf'
        source.write_bytes(b'%PDF-1.4\ncontrolled metadata input\n%%EOF\n')
        imported = self.call('import_sources', {'path': str(source)})
        profile = self.call('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})
        edition = next(e for e in imported['editions'] if e['source_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest())
        run = self.call('create_run', {'edition_id': edition['edition_id'],
                        'name': 'Účetní stopa', 'profile_path': profile['path'], 'profile_sha256': profile['sha256']})
        self.run_id = run['project']['run_id']
        self.image = self.directory / 'image.png'
        self.image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aR1sAAAAASUVORK5CYII='))

    def call(self, operation, payload=None):
        response = self.app.dispatch(operation, payload)
        self.assertTrue(response['ok'], response)
        return response['data']

    def diagnostic(self, **scenario):
        self.app.close()
        path = self.directory / 'scenario.json'
        path.write_text(json.dumps(scenario), encoding='utf-8')
        fixture = ROOT / 'tests/metrics_app_server_fixture.py'
        self.app = Application(self.registry, codex_runtime={
            'command': [sys.executable, str(fixture), str(path)], 'version': 'metrics-controlled-1',
            'kind': 'controlled_process_fixture', 'files': [
                {'path': str(fixture), 'sha256': hashlib.sha256(fixture.read_bytes()).hexdigest()}]})
        self.call('start_model_diagnostic', {'run_id': self.run_id, 'image_path': str(self.image)})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = self.call('model_diagnostic_status', {'run_id': self.run_id})
            if result['state'] not in ('starting', 'running'):
                return result
            time.sleep(.02)
        self.fail('Controlled process did not terminate')

    def archive(self, rows, **scenario):
        path = self.directory / 'archive.json'
        path.write_text(json.dumps({'rows': rows, **scenario}))
        subprocess.run([sys.executable, str(ROOT / 'tests/metrics_artifact_fixture.py'),
                        str(self.registry), self.run_id, str(path)], check=True)

    def frames(self):
        def row(direction, message, second, connection='one'):
            return {'direction': direction, 'message': message, 'connection_id': connection,
                    'timestamp': f'2026-10-16T10:00:{second:02d}+00:00', 'elapsed_seconds': second}
        return row, [row('client', {'id': 1, 'method': 'initialize'}, 0),
            row('client', {'id': 2, 'method': 'thread/start'}, 1),
            row('server', {'id': 2, 'result': {'thread': {'id': 'archive-thread'}}}, 2),
            row('client', {'id': 3, 'method': 'turn/start', 'params': {'threadId': 'archive-thread'}}, 5),
            row('server', {'id': 3, 'result': {'turn': {'id': 'archive-turn'}}}, 6)]

    def usage_event(self, total=None, turn='archive-turn'):
        return {'method': 'thread/tokenUsage/updated', 'params': {'threadId': 'archive-thread',
                'turnId': turn, 'tokenUsage': {'total': counters() if total is None else total}}}

    def test_cumulative_duplicate_usage_price_provenance_and_restart(self):
        result = self.diagnostic(snapshots=[counters(60, 10, 5, 20, 10), counters(), counters()],
                                 last=counters(1, 0, 0, 1, 0))
        self.assertEqual(result['state'], 'completed')
        metrics = self.call('run_metrics', {'run_id': self.run_id})
        self.assertEqual(metrics['tokens']['values'], {'noncached_input': 80, 'cached_input': 20, 'output': 50})
        self.assertEqual(metrics['tokens']['reasoning_output'], 30)
        self.assertEqual(metrics['tokens']['status'], 'observed')
        self.assertAlmostEqual(metrics['cost']['usd'], .000667, places=9)
        step = metrics['steps'][0]
        self.assertEqual(step['attempt_id'], result['attempt_id'])
        self.assertEqual(step['thread_id'], 'metrics-thread')
        self.assertEqual(step['turn_ids'], ['metrics-turn'])
        self.assertEqual(len(step['usage_sources']), 3)
        self.assertEqual(step['usage_sources'][-1]['disposition'], 'duplicate')
        detail = self.call('step_detail', {'run_id': self.run_id, 'step_id': step['step_id']})
        self.assertIn('prompt', detail['attempt'])
        self.assertEqual(detail['attempt']['answer'], 'Controlled accounting answer')
        self.assertEqual(detail['price_card']['model'], 'gpt-6.1-sol')
        ledger = self.registry / metrics['artifacts']['ledger']
        self.assertTrue(ledger.is_file())
        self.assertEqual(json.loads(ledger.read_text())['source_hash'], metrics['source_hash'])
        self.app.close()
        self.app = Application(self.registry)
        restored = self.call('run_metrics', {'run_id': self.run_id})
        self.assertEqual(restored['tokens'], metrics['tokens'])
        self.assertEqual(restored['cost'], metrics['cost'])
        self.assertEqual(restored['source_hash'], metrics['source_hash'])

    def test_missing_cache_write_is_unknown_price_and_interruption_retains_observation(self):
        total = counters()
        del total['cacheWriteInputTokens']
        self.diagnostic(snapshots=[total], state='interrupted')
        metrics = self.call('run_metrics', {'run_id': self.run_id})
        self.assertEqual(metrics['tokens']['values']['output'], 50)
        self.assertEqual(metrics['tokens']['status'], 'partial')
        self.assertIsNone(metrics['tokens']['cache_write_input'])
        self.assertIsNone(metrics['cost']['usd'])
        self.assertEqual(metrics['steps'][0]['state'], 'interrupted')

    def test_absent_usage_and_local_cache_are_not_zero(self):
        self.diagnostic(snapshots=[], state='interrupted')
        metrics = self.call('run_metrics', {'run_id': self.run_id})
        self.assertIsNone(metrics['tokens']['values'])
        self.assertIsNone(metrics['cost']['usd'])
        self.assertIsNone(metrics['per_page']['usd'])
        self.assertIsNone(metrics['steps'][0]['timing']['waiting_seconds'])
        self.assertIsNotNone(metrics['steps'][0]['timing']['startup_seconds'])

    def test_decreasing_or_compacted_counters_cannot_become_complete(self):
        for compact in (False, True):
            with self.subTest(compact=compact):
                # Each subcase uses an independent registry, not an accumulated fixture run.
                if compact:
                    self.app.close()
                    self.setUp()
                events = []
                if compact:
                    events.append({'method': 'thread/compacted', 'params': {'threadId': 'metrics-thread'}})
                events.append({'method': 'thread/tokenUsage/updated', 'params': {'threadId': 'metrics-thread',
                    'turnId': 'metrics-turn', 'tokenUsage': {'total': counters(50, 10, 5, 20, 10)}}})
                self.diagnostic(snapshots=[counters()], events=events)
                metrics = self.call('run_metrics', {'run_id': self.run_id})
                self.assertEqual(metrics['tokens']['status'], 'partial')
                self.assertIsNone(metrics['tokens']['values'])
                self.assertIsNone(metrics['cost']['usd'])

    def test_delayed_observation_is_kept_with_original_mapping(self):
        # Provider emission timestamps identify an older observation delivered later.
        newer = {'method': 'thread/tokenUsage/updated', 'emittedAtMs': 200,
                 'params': {'threadId': 'metrics-thread', 'turnId': 'metrics-turn',
                            'tokenUsage': {'total': counters()}}}
        older = {'method': 'thread/tokenUsage/updated', 'emittedAtMs': 100,
                 'params': {'threadId': 'metrics-thread', 'turnId': 'metrics-turn',
                            'tokenUsage': {'total': counters(60, 10, 5, 20, 10)}}}
        self.diagnostic(snapshots=[], events=[newer, older, newer])
        metrics = self.call('run_metrics', {'run_id': self.run_id})
        self.assertEqual(metrics['tokens']['values']['output'], 50)
        sources = metrics['steps'][0]['usage_sources']
        self.assertEqual([v['disposition'] for v in sources], ['observed', 'delayed_observation', 'duplicate'])
        self.assertTrue(all(s['thread_id'] == 'metrics-thread' and s['turn_id'] == 'metrics-turn' for s in sources))

    def test_multiple_connection_bootstrap_resume_and_partial_tail_stay_auditable(self):
        row, rows = self.frames()
        rows.insert(0, row('client', {'id': 1, 'method': 'initialize'}, 0, 'bootstrap'))
        rows.append(row('server', self.usage_event(), 10))
        rows.extend([row('client', {'id': 1, 'method': 'initialize'}, 11, 'resumed'),
            row('client', {'id': 2, 'method': 'thread/resume', 'params': {'threadId': 'archive-thread'}}, 12, 'resumed'),
            row('server', {'id': 2, 'result': {'thread': {'id': 'archive-thread'}}}, 13, 'resumed'),
            row('client', {'id': 3, 'method': 'turn/start', 'params': {'threadId': 'archive-thread'}}, 14, 'resumed'),
            row('server', {'id': 3, 'result': {'turn': {'id': 'recovery-turn'}}}, 15, 'resumed'),
            row('server', self.usage_event(counters(120, 20, 10, 60, 30), 'recovery-turn'), 18, 'resumed')])
        self.archive(rows, namespace='context-attempts', tail='{"direction":',
                     attempt={'operation': 'context_diagnostic'})
        metrics = self.call('run_metrics', {'run_id': self.run_id})
        self.assertEqual(len(metrics['steps']), 1)
        step = metrics['steps'][0]
        self.assertEqual(step['tokens']['status'], 'partial')
        self.assertIsNone(step['tokens']['values'])
        self.assertEqual(len(step['usage_sources']), 2)
        self.assertNotEqual(step['usage_sources'][0]['epoch'], step['usage_sources'][1]['epoch'])
        self.assertIn('Incomplete JSONL tail', ' '.join(metrics['warnings']))

    def test_nested_tool_time_is_not_added_to_active_time_and_wrong_model_has_no_price(self):
        row, rows = self.frames()
        for identifier, start, end in [('outer', 7, 15), ('inner', 9, 12)]:
            item = {'id': identifier, 'type': 'mcpToolCall'}
            rows.extend([row('server', {'method': 'item/started', 'params': {'item': item}}, start),
                         row('server', {'method': 'item/completed', 'params': {'item': item}}, end)])
        rows.append(row('server', self.usage_event(), 19))
        rows.sort(key=lambda r: r['timestamp'])
        self.archive(rows, attempt={'effective': {'model': 'unknown-model'},
            'waiting_intervals': [['2026-10-16T10:00:00+00:00', '2026-10-16T10:00:05+00:00']]})
        metrics = self.call('run_metrics', {'run_id': self.run_id})
        step = metrics['steps'][0]
        self.assertEqual(step['timing']['wall_seconds'], 20)
        self.assertEqual(step['timing']['active_seconds'], 15)
        self.assertEqual(step['timing']['waiting_seconds'], 5)
        self.assertEqual(step['timing']['tool_seconds'], 8)
        self.assertEqual(metrics['timing']['active_seconds'], 15)
        self.assertIsNone(metrics['cost']['usd'])
        self.assertIn('No exact-model', step['cost']['reason'])

    def test_local_unit_and_cache_times_have_stable_ids_and_no_ai_usage(self):
        row, rows = self.frames()
        rows.append(row('server', self.usage_event(), 19))
        events = []
        for sid, start, end, terminal in [('raster:page:1', 2, 10, 'unit_completed'),
                                          ('ocr:page:1:psm:3', 7, 12, 'unit_cached')]:
            for kind, second in [('unit_started', start), (terminal, end)]:
                events.append({'event_id': sid + ':' + kind, 'type': kind, 'step_id': sid,
                    'timestamp': f'2026-10-16T10:00:{second:02d}+00:00', 'duration_seconds': end - start})
        self.archive(rows, preparation={'events': events}, attempt={
            'waiting_intervals': [['2026-10-16T10:00:00+00:00', '2026-10-16T10:00:05+00:00']]})
        metrics = self.call('run_metrics', {'run_id': self.run_id})
        local = [s for s in metrics['steps'] if s['kind'] == 'local']
        self.assertEqual(len(local), 2)
        self.assertEqual(local[1]['state'], 'cached')
        self.assertTrue(all(s['tokens']['status'] == 'not_applicable' and s['tokens']['values'] is None for s in local))
        self.assertEqual(metrics['tokens']['values']['output'], 50)
        self.assertEqual(metrics['timing']['active_seconds'], 18)  # union [2,12] and [5,20]
        self.assertEqual(metrics['timing']['waiting_seconds'], 2)  # active work excludes overlapping waiting
        self.assertEqual(metrics['timing']['observed_span_seconds'], 20)
        self.assertEqual(metrics['timing']['unattributed_seconds'], 0)
        detail = self.call('step_detail', {'run_id': self.run_id, 'step_id': local[0]['step_id']})
        self.assertEqual(len(detail['events']), 2)
        self.assertEqual(detail['events'][0]['step_id'], 'raster:page:1')

    def test_large_original_stream_is_paged_without_losing_provenance(self):
        self.diagnostic(snapshots=[counters()] * 205)
        metrics = self.call('run_metrics', {'run_id': self.run_id})
        step = metrics['steps'][0]
        self.assertEqual(step['usage_source_total'], 205)
        self.assertLessEqual(len(step['usage_sources']), 5)
        first = self.call('step_detail', {'run_id': self.run_id, 'step_id': step['step_id'], 'limit': 100})
        second = self.call('step_detail', {'run_id': self.run_id, 'step_id': step['step_id'], 'offset': 100, 'limit': 100})
        self.assertEqual(first['usage_next_offset'], 100)
        self.assertEqual(second['usage_next_offset'], 200)
        self.assertNotEqual(first['usage_sources'][0]['line'], second['usage_sources'][0]['line'])
        self.assertIn('original', first['usage_sources'][0])
        rejected = self.app.dispatch('step_detail', {'run_id': self.run_id, 'step_id': step['step_id'], 'limit': 10000})
        self.assertFalse(rejected['ok'])
        self.assertEqual(rejected['error']['code'], 'invalid_request')

    def test_replayed_identical_turn_in_another_attempt_is_not_new_consumption(self):
        row, rows = self.frames()
        rows.append(row('server', self.usage_event(), 19))
        self.archive(rows, attempt_id='first')
        self.archive(rows, attempt_id='replayed')
        metrics = self.call('run_metrics', {'run_id': self.run_id})
        self.assertEqual(len(metrics['steps']), 2)
        self.assertEqual(metrics['tokens']['values']['output'], 50)
        self.assertEqual(metrics['steps'][1]['duplicate_of'], metrics['steps'][0]['step_id'])
        self.assertAlmostEqual(metrics['cost']['usd'], .000667)

    def test_two_turns_are_mapped_without_summing_thread_snapshots(self):
        row, rows = self.frames()
        rows.extend([row('server', self.usage_event(counters(60, 10, 5, 20, 10)), 10),
            row('client', {'id': 4, 'method': 'turn/start', 'params': {'threadId': 'archive-thread'}}, 11),
            row('server', {'id': 4, 'result': {'turn': {'id': 'second-turn'}}}, 12),
            row('server', self.usage_event(turn='second-turn'), 19)])
        self.archive(rows)
        metrics = self.call('run_metrics', {'run_id': self.run_id})
        self.assertEqual(metrics['tokens']['values']['output'], 50)
        self.assertEqual(metrics['steps'][0]['turn_ids'], ['archive-turn', 'second-turn'])
        self.assertEqual([s['turn_id'] for s in metrics['steps'][0]['usage_sources']], ['archive-turn', 'second-turn'])

    def test_client_compaction_boundary_is_unknown_even_when_totals_increase(self):
        row, rows = self.frames()
        rows.extend([row('server', self.usage_event(), 10),
            row('client', {'id': 4, 'method': 'thread/compact/start', 'params': {'threadId': 'archive-thread'}}, 11),
            row('server', self.usage_event(counters(120, 20, 10, 60, 30)), 19)])
        self.archive(rows)
        metrics = self.call('run_metrics', {'run_id': self.run_id})
        self.assertIsNone(metrics['tokens']['values'])
        self.assertEqual(len(metrics['steps'][0]['usage_sources']), 2)

    def test_price_per_page_uses_real_preparation_count_and_survives_restart(self):
        import fitz
        from PIL import Image, ImageDraw
        image = Image.new('RGB', (300, 90), 'white')
        ImageDraw.Draw(image).text((20, 25), 'METRICS 21', fill='black', font_size=28)
        raster = io.BytesIO()
        image.save(raster, format='PNG')
        source = self.directory / 'two independent raster pages.pdf'
        with fitz.open() as document:
            for _ in range(2):
                page = document.new_page(width=72, height=21.6)
                page.insert_image(page.rect, stream=raster.getvalue())
            document.save(source)
        imported = self.call('import_sources', {'path': str(source)})
        profile = self.call('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})
        edition = next(e for e in imported['editions'] if e['source_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest())
        run = self.call('create_run', {'edition_id': edition['edition_id'],
            'name': 'Dvě skutečné stránky', 'profile_path': profile['path'], 'profile_sha256': profile['sha256']})
        self.run_id = run['project']['run_id']
        self.call('start_preparation', {'run_id': self.run_id})
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            prepared = self.call('preparation_status', {'run_id': self.run_id})
            if prepared['state'] not in ('starting', 'running'):
                break
            time.sleep(.05)
        self.assertEqual(prepared['state'], 'completed', prepared)
        self.diagnostic(snapshots=[counters()])
        metrics = self.call('run_metrics', {'run_id': self.run_id})
        self.assertEqual(metrics['per_page']['page_count'], 2)
        self.assertAlmostEqual(metrics['per_page']['usd'], .000667 / 2)
        self.assertTrue(any(s['kind'] == 'local' for s in metrics['steps']))
        self.app.close()
        self.app = Application(self.registry)
        self.assertEqual(self.call('run_metrics', {'run_id': self.run_id})['per_page'], metrics['per_page'])


if __name__ == '__main__':
    unittest.main()
