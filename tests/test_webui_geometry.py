"""Geometry preparation at the application's public request/artifact seam."""
from pathlib import Path
import sys
import unittest
import json
import hashlib
import os
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import test_webui_reading as reading_fixture


class GeometryTests(unittest.TestCase):
    setUp = reading_fixture.WebUIReadingTests.setUp
    peer = reading_fixture.WebUIReadingTests.peer
    put = reading_fixture.WebUIReadingTests.put
    wait = reading_fixture.WebUIReadingTests.wait

    def test_geometry_requires_a_verified_first_reading_before_any_preparation(self):
        result = self.app.dispatch('start_geometry', {'run_id': self.identifier})
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['error']['code'], 'geometry_reading_required')
        self.assertFalse((self.work / 'geometry-preparation.json').exists())

    def test_native_geometry_patch_preserves_historical_reading_and_rejects_stale_cas(self):
        self.peer()
        self.assertTrue(self.app.dispatch('start_reading', {'run_id': self.identifier})['ok'])
        reading = self.wait()
        self.assertTrue(reading['reading_complete'], reading)
        original = json.loads((self.work / 'review.json').read_text())
        line = dict(original['lines'][0], selection_region=[1, 1, 89, 19])
        payload = {'run_id': self.identifier, 'expected_review_sha256': reading['review_sha256'],
            'patch': {'lines': [{'line': line}]}}
        changed = self.app.dispatch('patch_geometry', payload)
        self.assertTrue(changed['ok'], changed)
        historical = self.app.dispatch('reading_status', {'run_id': self.identifier})['data']
        self.assertTrue(historical['reading_complete'], historical)
        self.assertFalse(historical['current_review_bound'])
        self.assertEqual(historical['review_sha256'], reading['review_sha256'])
        stale = self.app.dispatch('patch_geometry', payload)
        self.assertFalse(stale['ok'], stale)
        self.assertEqual(stale['error']['code'], 'review_changed')

    def native_geometry_peer(self, mode='success'):
        self.peer()
        from PIL import Image, ImageDraw
        native_path = Path(os.environ.get('OCR_ENVIRONMENT', ROOT/'native/environment.json'))
        native = json.loads(native_path.read_text())
        identity = {'build_id': native['build_id'], 'manifest_sha256': hashlib.sha256(native_path.read_bytes()).hexdigest()}
        manifest = json.loads((self.work/'input-manifest.json').read_text())
        manifest.update(dpi=300, ocr={'language': 'ces'}, environment=identity)
        for page in manifest['pages']:
            image = Image.new('RGB', (100, 100), 'white')
            ImageDraw.Draw(image).text((3, 3), 'ABC' if page['page']==1 else 'DEF', fill='black')
            path = self.work/'raster'/f"page-{page['page']}.png"
            image.save(path)
            page['raster_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.put(self.work/'input-manifest.json', manifest)
        candidates = json.loads((self.work/'local-candidates.json').read_text())
        for region in candidates:
            region['lines'][0]['words'] = []
        self.put(self.work/'local-candidates.json', candidates)
        checkpoint = json.loads((self.work/'preparation-checkpoint.json').read_text())
        checkpoint['identity']['environment'] = identity
        checkpoint['outputs'] = {name: hashlib.sha256((self.work/name).read_bytes()).hexdigest() for name in checkpoint['outputs']}
        self.put(self.work/'preparation-checkpoint.json', checkpoint)
        history = self.root/self.run['artifacts']['history']['path']
        events = [json.loads(line) for line in history.read_text().splitlines()]
        for event in events:
            if event.get('type')=='step_completed':
                event['environment'] = identity
            if event.get('type')=='checkpoint_completed':
                event['checkpoint_sha256'] = hashlib.sha256((self.work/'preparation-checkpoint.json').read_bytes()).hexdigest()
        history.write_text(''.join(json.dumps(e)+'\n' for e in events))
        self.assertTrue(self.app.dispatch('start_reading', {'run_id': self.identifier})['ok'])
        self.assertTrue(self.wait()['reading_complete'])
        fixture = ROOT/'tests/geometry_app_server_fixture.py'
        geometry = self.app.geometry
        geometry.runtime = {'kind': 'controlled_process_fixture', 'command': [sys.executable, str(fixture), mode],
            'files': [{'path': str(fixture), 'sha256': hashlib.sha256(fixture.read_bytes()).hexdigest()}]}
        # These historical readiness artifacts explicitly belong to the controlled peer.
        for namespace in ['codex-attempts', 'context-attempts']:
            path = self.work/'application'/namespace/'preflight/attempt.json'
            value = json.loads(path.read_text())
            value['runtime'] = geometry.runtime
            self.put(path, value)

    def geometry_wait(self):
        deadline = time.monotonic()+30
        while time.monotonic()<deadline:
            result = self.app.dispatch('geometry_status', {'run_id': self.identifier})
            self.assertTrue(result['ok'], result)
            if result['data']['state'] not in ('starting', 'running'):
                return result['data']
            time.sleep(.03)
        self.fail('Geometry fixture did not finish')

    def test_actual_stage_contract_commits_independent_samples_then_publishes_only_original_observations(self):
        self.native_geometry_peer()
        started = self.app.dispatch('start_geometry', {'run_id': self.identifier})
        self.assertTrue(started['ok'], started)
        result = self.geometry_wait()
        self.assertEqual(result['state'], 'completed', result)
        self.assertTrue(result['geometry_complete'])
        self.assertEqual(result['counts']['samples'], 2)
        self.assertEqual(json.loads((self.work/'samples.json').read_text())[0]['expected'], 'ABC')
        self.assertTrue(self.app.dispatch('reading_status', {'run_id': self.identifier})['data']['reading_complete'])
        metrics = self.app.dispatch('run_metrics', {'run_id': self.identifier})
        self.assertTrue(metrics['ok'], metrics)
        steps = [s for s in metrics['data']['steps'] if s['operation']=='geometry']
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]['tokens']['values']['noncached_input'], 206)
        self.assertIsNone(steps[0]['tokens']['cache_write_input'])
        self.assertEqual(len(steps[0]['usage_sources']), 2)
        denied = self.app.dispatch('open_geometry_artifact', {'run_id': self.identifier, 'path': '../../inputs/private.pdf'})
        self.assertFalse(denied['ok'], denied)
        (self.work/'checks/geometry-review-001.png').write_bytes(b'tampered diagnostic pixels')
        invalid = self.app.dispatch('geometry_status', {'run_id': self.identifier})
        self.assertFalse(invalid['data']['geometry_complete'], invalid)
        self.assertEqual(invalid['data']['state'], 'invalidated')

    def test_completed_but_incomplete_visual_answer_never_publishes_a_geometry_checkpoint(self):
        self.native_geometry_peer('missing_line')
        self.assertTrue(self.app.dispatch('start_geometry', {'run_id': self.identifier})['ok'])
        result = self.geometry_wait()
        self.assertEqual(result['state'], 'failed', result)
        self.assertFalse(result['geometry_complete'])
        self.assertFalse((self.work/'geometry-checkpoint.json').exists())
        self.assertTrue(result['prepared_artifacts_valid'])
        self.assertEqual(result['turns'][-1]['state'], 'completed')
        self.assertTrue((self.work/'geometry-source-samples.json').exists())

    def test_explicit_continuation_reuses_committed_source_samples_without_another_source_turn(self):
        self.native_geometry_peer('missing_line')
        self.assertTrue(self.app.dispatch('start_geometry', {'run_id': self.identifier})['ok'])
        failed = self.geometry_wait()
        samples = (self.work/'geometry-source-samples.json').read_bytes()
        denied = self.app.dispatch('start_geometry', {'run_id': self.identifier})
        self.assertFalse(denied['ok'], denied)
        self.assertEqual(denied['error']['code'], 'geometry_reconciliation_required')
        self.app.geometry.runtime['command'][-1] = 'success'
        for namespace in ['codex-attempts', 'context-attempts']:
            path = self.work/'application'/namespace/'preflight/attempt.json'
            value = json.loads(path.read_text()); value['runtime'] = self.app.geometry.runtime
            self.put(path, value)
        continued = self.app.dispatch('start_geometry', {'run_id': self.identifier, 'previous_attempt_id': failed['attempt_id']})
        self.assertTrue(continued['ok'], continued)
        result = self.geometry_wait()
        self.assertEqual(result['state'], 'completed', result)
        self.assertEqual([turn['stage'] for turn in result['turns']], ['geometry_examination'])
        self.assertEqual((self.work/'geometry-source-samples.json').read_bytes(), samples)


if __name__ == '__main__':
    unittest.main()
