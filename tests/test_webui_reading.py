"""First visual reading through the same public operations used by the GUI."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.service import Application


class WebUIReadingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='První vizuální čtení ')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.root = self.directory / 'registry'
        self.app = Application(self.root)
        self.addCleanup(lambda: self.app.close())
        source = self.directory / 'source.pdf'
        source.write_bytes(b'%PDF-1.4\ncontrolled reading source\n%%EOF\n')
        edition = self.app.dispatch('import_sources', {'path': str(source)})['data']['editions'][0]
        profile = self.app.dispatch('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})['data']
        self.run = self.app.dispatch('create_run', {'edition_id': edition['edition_id'], 'name': 'Vizuální čtení',
            'profile_path': profile['path'], 'profile_sha256': profile['sha256']})['data']
        self.identifier = self.run['project']['run_id']
        self.work = self.root / self.run['artifacts']['workspace']['path']

    def test_unprepared_source_and_missing_real_preflight_never_submit_a_reading_turn(self):
        missing = self.app.dispatch('start_reading', {'run_id': self.identifier})
        self.assertFalse(missing['ok'])
        self.assertEqual(missing['error']['code'], 'reading_preflight_required')
        status = self.app.dispatch('reading_status', {'run_id': self.identifier})
        self.assertTrue(status['ok'], status)
        self.assertEqual(status['data']['state'], 'not_started')
        self.assertFalse((self.work / 'review.json').exists())

    def test_valid_model_preflight_does_not_replace_verified_native_source_preparation(self):
        self.peer()
        (self.work / 'preparation-checkpoint.json').unlink(missing_ok=True)
        started = self.app.dispatch('start_reading', {'run_id': self.identifier})
        self.assertFalse(started['ok'], started)
        self.assertEqual(started['error']['code'], 'reading_preparation_required')
        self.assertEqual(self.app.dispatch('reading_status', {'run_id': self.identifier})['data']['state'], 'not_started')

    def peer(self, mode='success'):
        """Controlled old public proof artifacts; never counted as native evidence."""
        self.app.close()
        fixture = ROOT / 'tests/reading_app_server_fixture.py'
        runtime = {'kind': 'controlled_process_fixture', 'version': 'reading-fixture-15',
            'command': [sys.executable, str(fixture), mode],
            'files': [{'path': str(fixture), 'sha256': hashlib.sha256(fixture.read_bytes()).hexdigest()}]}
        context_runtime = {'kind': 'controlled_process_fixture', 'package': str(self.directory), 'node': sys.executable,
            'files': [], 'interpreters': [], 'probe_command': [sys.executable, '-c',
                'print(\'{"node":"fixture","sqlite_fts5":true}\')']}
        self.app = Application(self.root, codex_runtime=runtime, context_runtime=context_runtime)
        source_hash = self.run['project']['source_sha256']
        pages = []
        candidates = []
        for page in [1, 2]:
            path = self.work / 'raster' / f'page-{page}.png'
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b'controlled source image ' + str(page).encode())
            pages.append({'page': page, 'raster_size': [100, 100],
                'raster_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
            candidates.append({'id': 'region-' + str(page), 'page': page,
                'lines': [{'id': 'candidate-' + str(page), 'page': page, 'text': 'WRONG OCR'}]})
        self.put(self.work / 'input-manifest.json', {'source_sha256': source_hash, 'pages': pages})
        self.put(self.work / 'local-candidates.json', candidates)
        self.put(self.work / 'ocr-commands.json', [])
        self.put(self.work / 'fresh-lines.json', [line for region in candidates for line in region['lines']])
        self.put(self.work / 'preparation-identity.json', {})
        outputs = ['input-manifest.json', 'ocr-commands.json', 'fresh-lines.json', 'preparation-identity.json']
        for number in [1, 2]:
            for name in [f'raster/overview-{number}.png', f'raster/page-{number}-checkpoint.json'] + [
                f'ocr/page-{number}-psm{psm}{suffix}' for psm in [3, 11]
                for suffix in ['.hocr', '.tsv', '.txt', '.box', '-cache.json']]:
                path = self.work / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'controlled preparation output')
                outputs.append(name)
            outputs.append(f'raster/page-{number}.png')
        identity = {'source_sha256': source_hash, 'dpi': 300, 'language': 'ces',
            'environment': {'build_id': 'controlled-preparation', 'manifest_sha256': 'f' * 64}}
        self.put(self.work / 'preparation-checkpoint.json', {'status': 'completed', 'identity': identity,
            'counts': {'pages': 2}, 'outputs': {name: hashlib.sha256((self.work / name).read_bytes()).hexdigest() for name in outputs}})
        preparation = {'attempt_id': 'controlled-preparation', 'root': str(self.root), 'run_id': self.identifier,
            'state': 'completed', 'started_at': '2026-01-01T00:00:00+00:00', 'ended_at': '2026-01-01T00:00:01+00:00',
            'history': self.run['artifacts']['history']['path'], 'expected': {**identity,
                'source_path': str(self.root / self.run['artifacts']['source']['path'])}}
        self.put(self.work / 'application/attempts/controlled-preparation.json', preparation)
        history = self.root / preparation['history']
        with history.open('a') as stream:
            for event in [
                {'type': 'step_completed', 'environment': identity['environment']},
                {'type': 'checkpoint_completed', 'checkpoint_sha256': hashlib.sha256((self.work / 'preparation-checkpoint.json').read_bytes()).hexdigest()}]:
                stream.write(json.dumps({'attempt_id': preparation['attempt_id'], 'step_id': 'environment',
                    'timestamp': preparation['ended_at'], **event}) + '\n')
        workspace, storage = self.work / 'context/workspace', self.work / 'context/store'
        workspace.mkdir(parents=True, exist_ok=True)
        for name in ['content', 'sessions']:
            (storage / name).mkdir(parents=True, exist_ok=True)
            (storage / name / 'fixture.db').unlink(missing_ok=True)
        with closing(sqlite3.connect(storage / 'content/fixture.db')) as db, db:
            db.executescript('CREATE VIRTUAL TABLE chunks USING fts5(content); CREATE TABLE sources(id);')
            db.execute('INSERT INTO chunks VALUES(?)', ('CONTEXT_DIAGNOSTIC_RECORD fixture-oracle',))
        with closing(sqlite3.connect(storage / 'sessions/fixture.db')) as db, db:
            db.executescript('CREATE TABLE session_meta(session_id,project_dir,compact_count);'
                'CREATE TABLE session_events(session_id); CREATE TABLE session_resume(session_id,snapshot,event_count,consumed);')
            db.execute('INSERT INTO session_meta VALUES(?,?,1)', ('fixture-context', str(workspace)))
            db.execute('INSERT INTO session_events VALUES(?)', ('fixture-context',))
            db.execute('INSERT INTO session_resume VALUES(?,?,1,0)', ('fixture-context', 'fixture snapshot'))
        common = {'schema_version': 1, 'attempt_id': 'preflight', 'root': str(self.root),
            'run_id': self.identifier, 'state': 'completed', 'started_at': '2026-01-01T00:00:00+00:00',
            'image': None, 'profile_sha256': self.run['run']['profile_sha256'], 'runtime': runtime,
            'error': None, 'native_runtime': False}
        model = {**common, 'operation': 'vision_diagnostic', 'combination_verified': True}
        self.put(self.work / 'application/codex-attempts/preflight/attempt.json', model)
        items = [
            {'type': 'commandExecution', 'status': 'completed', 'exitCode': 0,
             'command': 'echo routed', 'aggregatedOutput': 'context-mode: Build tool redirected.'},
            {'type': 'mcpToolCall', 'server': 'context_mode', 'tool': 'ctx_execute', 'status': 'completed',
             'arguments': {'language': 'shell', 'code': './gradlew --context-diagnostic'}},
            {'type': 'mcpToolCall', 'server': 'context_mode', 'tool': 'ctx_search', 'status': 'completed',
             'result': {'content': [{'text': 'fixture-oracle'}]}}]
        context = {**common, 'operation': 'context_diagnostic', 'context_verified': True,
            'context_runtime': context_runtime, 'oracle': 'fixture-oracle', 'thread_id': 'fixture-context',
            'diagnostic_input': {'bytes': 50}, 'context_paths': {'workspace': str(workspace), 'storage': str(storage)},
            'turns': [{'stage': 'routing', 'turn_id': 'fixture-routing'}],
            'completed_items': [{'turnId': 'fixture-routing', 'item': item} for item in items],
            'hook_events': [{'method': 'hook/completed', 'params': {'run': {'eventName': event, 'status': 'completed'}}}
                for event in ['sessionStart', 'preToolUse', 'postToolUse', 'userPromptSubmit', 'stop']]}
        self.put(self.work / 'application/context-attempts/preflight/attempt.json', context)

    def put(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False))

    def wait(self):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = self.app.dispatch('reading_status', {'run_id': self.identifier})
            self.assertTrue(result['ok'], result)
            if result['data']['state'] not in ('starting', 'running'):
                return result['data']
            time.sleep(.02)
        self.fail('Controlled reading did not finish')

    def test_all_source_images_precede_candidates_and_only_validated_model_json_is_published(self):
        self.peer()
        started = self.app.dispatch('start_reading', {'run_id': self.identifier})
        self.assertTrue(started['ok'], started)
        result = self.wait()
        self.assertEqual(result['state'], 'completed', result)
        self.assertTrue(result['reading_complete'])
        review = json.loads((self.work / 'review.json').read_text())
        self.assertEqual([line['text'] for line in review['lines']], ['ABC', 'DEF'])
        self.assertEqual([line['text_status'] for line in review['lines']], ['visually_confirmed'] * 2)
        proposal = json.loads((self.root / result['artifacts']['proposal']).read_text())
        self.assertEqual(review, proposal['review'])
        protocol = [json.loads(line)['message'] for line in (self.root / result['artifacts']['protocol']).read_text().splitlines()]
        turns = [m['params'] for m in protocol if m.get('method') == 'turn/start']
        self.assertEqual(len(turns), 2)
        self.assertEqual(len([item for item in turns[0]['input'] if item['type'] == 'localImage']), 2)
        self.assertNotIn('WRONG OCR', json.dumps(turns[0]))
        self.assertEqual(result['coverage']['source_turn_id'], 'source-turn')
        self.app.close()
        self.app = Application(self.root)
        restored = self.app.dispatch('reading_status', {'run_id': self.identifier})
        self.assertEqual(restored['data']['attempt_id'], result['attempt_id'])
        self.assertTrue(restored['data']['reading_complete'])

    def test_partial_source_or_final_and_wrong_model_publish_nothing(self):
        for mode, code in [('partial_source', 'reading_source_incomplete'),
                ('partial_final', 'reading_validation_missing'), ('wrong_model', 'model_configuration_mismatch')]:
            with self.subTest(mode=mode):
                self.peer(mode)
                started = self.app.dispatch('start_reading', {'run_id': self.identifier})
                self.assertTrue(started['ok'], started)
                result = self.wait()
                self.assertEqual(result['state'], 'failed', result.get('error'))
                self.assertEqual(result['error']['code'], code)
                self.assertFalse(result['reading_complete'])
                self.assertFalse((self.work / 'review.json').exists())

    def test_original_protocol_and_source_tampering_invalidate_saved_reading(self):
        self.peer()
        self.assertTrue(self.app.dispatch('start_reading', {'run_id': self.identifier})['ok'])
        result = self.wait()
        self.assertTrue(result['reading_complete'], result.get('error'))
        protocol = self.root / result['artifacts']['protocol']
        original = protocol.read_text()
        protocol.write_text(original.replace('ABC', 'XYZ'))
        changed = self.app.dispatch('reading_status', {'run_id': self.identifier})['data']
        self.assertEqual(changed['state'], 'invalidated')
        self.assertFalse(changed['reading_complete'])
        protocol.write_text(original)
        (self.work / 'raster/page-2.png').write_bytes(b'replaced source')
        changed = self.app.dispatch('reading_status', {'run_id': self.identifier})['data']
        self.assertEqual(changed['state'], 'invalidated')
        self.assertEqual(changed['error']['code'], 'reading_source_changed')

    def test_active_reading_keeps_registry_and_other_ai_operations_bound_to_its_owner(self):
        self.peer('slow')
        self.assertTrue(self.app.dispatch('start_reading', {'run_id': self.identifier})['ok'])
        changed = self.app.dispatch('open_registry', {'root': str(self.directory)})
        self.assertFalse(changed['ok'], changed)
        self.assertEqual(changed['error']['code'], 'operation_active')
        diagnostic = self.app.dispatch('start_model_diagnostic', {'run_id': self.identifier})
        self.assertEqual(diagnostic['error']['code'], 'operation_active')
        self.assertEqual(self.wait()['state'], 'completed')

    def test_model_authored_uncertainty_and_printed_mistake_survive_atomic_publication(self):
        self.peer('uncertain')
        self.assertTrue(self.app.dispatch('start_reading', {'run_id': self.identifier})['ok'])
        result = self.wait()
        self.assertTrue(result['reading_complete'], result.get('error'))
        review = json.loads((self.work / 'review.json').read_text())
        self.assertEqual(review['lines'][0]['text'], 'Dne [NEČITELNÉ]')
        self.assertEqual(review['unresolved'][0]['status'], 'waiting_for_input')
        self.assertEqual(review['publisher_errors'][0]['printed'], 'DEF')

    def test_reading_consumption_joins_existing_metrics_with_original_phase_and_connection_sources(self):
        self.peer()
        self.assertTrue(self.app.dispatch('start_reading', {'run_id': self.identifier})['ok'])
        result = self.wait()
        self.assertTrue(result['reading_complete'], result.get('error'))
        metrics = self.app.dispatch('run_metrics', {'run_id': self.identifier})
        self.assertTrue(metrics['ok'], metrics)
        reading = [step for step in metrics['data']['steps'] if step['operation'] == 'visual_reading']
        self.assertEqual(len(reading), 1)
        detail = self.app.dispatch('step_detail', {'run_id': self.identifier, 'step_id': reading[0]['step_id']})
        self.assertTrue(detail['ok'], detail)
        step = detail['data']
        self.assertEqual(step['tokens']['values'], {'noncached_input': 162, 'cached_input': 40, 'output': 20})
        self.assertEqual(step['tokens']['cache_write_input'], 0)
        self.assertEqual(step['tokens']['reasoning_output'], 10)
        self.assertEqual(step['turn_ids'], ['source-turn', 'accounting-turn'])
        self.assertEqual([source['connection_id'] for source in step['usage_sources']], ['1', '1'])
        self.assertTrue(all(source['path'].endswith('protocol.jsonl') for source in step['usage_sources']))


if __name__ == '__main__':
    unittest.main()
