"""Preserved geometry via public preview, correction and recovery operations."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import test_webui_corrections as scenarios
import test_webui_phase_preview as page_scenarios
import test_webui_export as export_scenarios


class GeometryPreviewTests(unittest.TestCase):
    setUp = scenarios.CorrectionTests.setUp
    start = scenarios.CorrectionTests.start
    wait = scenarios.CorrectionTests.wait
    correction = scenarios.CorrectionTests.correction

    def preview(self, page=1):
        result = self.app.dispatch('phase_preview', {'run_id': self.identifier, 'phase': 'geometry', 'page': page})
        self.assertTrue(result['ok'], result)
        return result['data']

    def test_original_geometry_survives_real_targeted_correction_restart_and_missing_history(self):
        self.start()
        before = self.preview()
        self.assertEqual(before['state'], 'available', before)
        self.assertEqual(before['overlays'][0]['text'], 'AXC')
        self.assertEqual(before['overlays'][0]['order'], 1)
        self.assertTrue(before['overlays'][0]['characters'])
        self.assertEqual(before['geometry_status'], 'approximation_requires_character_review')
        original = {p: p.read_bytes() for p in (self.work / 'phase-previews/geometry').rglob('*') if p.is_file()}
        status = self.correction()
        self.assertEqual(status['state'], 'completed', status)
        self.assertEqual(json.loads((self.work / 'reviewed-lines.json').read_text())[0]['text'], 'ABC')
        self.assertEqual(self.preview()['identity'], before['identity'])
        self.assertEqual(self.preview()['overlays'], before['overlays'])
        self.assertEqual({p: p.read_bytes() for p in original}, original)
        runtime = self.app.corrections.runtime
        self.app.close()
        from app.service import Application
        self.app = Application(self.root, codex_runtime=runtime, context_runtime=self.context)
        self.assertEqual(self.preview()['identity'], before['identity'])
        shutil.rmtree(self.work / 'phase-previews/geometry')
        missing = self.preview()
        self.assertEqual(missing['state'], 'historical_missing')
        self.assertEqual(missing['overlays'], [])


class GeometryPreviewCoordinatesTests(unittest.TestCase):
    setUp = page_scenarios.PhasePreviewTests.setUp
    prepare_fixture = page_scenarios.PhasePreviewTests.prepare_fixture
    preview = page_scenarios.PhasePreviewTests.preview

    def test_recorded_character_boxes_and_logical_order_follow_independent_crop_rotation_positions(self):
        self.prepare_fixture()
        archive = self.work / 'phase-previews/geometry'
        archive.mkdir(parents=True)
        source_manifest = json.loads((self.work / 'input-manifest.json').read_text())
        lines = [
            {'id': 'left', 'page': 1, 'text': 'L', 'selection_region': [80, 40, 140, 120],
                'cells': [{'text': 'L', 'selection_bbox': [80, 40, 140, 120]}]},
            {'id': 'right', 'page': 1, 'text': 'R', 'selection_region': [140, 40, 200, 120],
                'cells': [{'text': 'R', 'selection_bbox': [140, 40, 200, 120]}]},
            {'id': 'rotated', 'page': 2, 'text': 'AB', 'selection_region': [180, 60, 240, 180],
                'cells': [{'text': 'A', 'selection_bbox': [180, 60, 210, 180]},
                    {'text': 'B', 'selection_bbox': [210, 60, 240, 180]}]}]
        pages = [{'page': 1, 'units': [{'id': 'first', 'lines': [lines[1]]}, {'id': 'second', 'lines': [lines[0]]}]},
            {'page': 2, 'units': [{'id': 'third', 'lines': [lines[2]]}]}]
        values = {'input-manifest.json': source_manifest, 'reviewed-lines.json': lines, 'pages.json': pages,
            'geometry.json': [], 'review.json': {'source_sha256': self.edition['edition_id'], 'lines': lines},
            'segmented-review.json': {'lines': lines}, 'segment-manifest.json': {}}
        hashes = {}
        for name, value in values.items():
            path = archive / name; path.write_text(json.dumps(value)); hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        identity = {'run_id': self.run_id, 'source_sha256': self.edition['edition_id']}
        preparation = {'identity': identity, 'outputs': {name: hashes[name] for name in ['reviewed-lines.json', 'pages.json', 'geometry.json']},
            'inputs': {'review': {'sha256': hashes['review.json']}}}
        path = archive / 'geometry-preparation.json'; path.write_text(json.dumps(preparation)); hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        checkpoint = {'identity': identity, 'preparation_sha256': hashes['geometry-preparation.json']}
        path = archive / 'geometry-checkpoint.json'; path.write_text(json.dumps(checkpoint)); hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        (archive / 'manifest.json').write_text(json.dumps({'schema_version': 1, 'phase': 'geometry',
            'run_id': self.run_id, 'source_sha256': self.edition['edition_id'], 'files': hashes}))
        first = self.preview(phase='geometry')
        self.assertEqual(first['state'], 'available', first)
        self.assertEqual([(r['text'], r['order']) for r in first['overlays']], [('R', 1), ('L', 2)])
        rotated = self.preview(phase='geometry', page=2)
        self.assertEqual(rotated['overlays'][0]['order'], 3)
        for actual, expected in zip(rotated['overlays'][0]['normalized_bbox'], [.6, 30/260, .8, 90/260]):
            self.assertAlmostEqual(actual, expected, places=5)
        self.assertEqual(rotated['overlays'][0]['characters'][0]['normalized_bbox'][0:3:2], [.6, .7])
        self.assertEqual(rotated['image']['rotation'], 90)


class GeometryPreviewRecoveryTests(unittest.TestCase):
    setUp = export_scenarios.AutonomousExportTests.setUp

    def test_original_completed_geometry_recovery_creates_the_same_preserved_phase_without_ai(self):
        self.app.close()
        fixture = ROOT / 'tests/corrections_app_server_fixture.py'
        wrapper = self.directory / 'publication-blocked-peer.py'
        wrapper.write_text('import sys,runpy\nsys.argv.insert(1,"publication_blocked")\nrunpy.run_path(' + repr(str(fixture)) + ',run_name="__main__")\n')
        runtime = {**self.runtime, 'command': [sys.executable, '-B', str(wrapper)],
            'files': [*self.runtime['files'], *[{'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in [fixture, wrapper]]]}
        from app.service import Application
        self.app = Application(self.root, codex_runtime=runtime, context_runtime=self.context)
        profile = self.app.dispatch('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})['data']
        started = self.app.dispatch('start_autonomous', {'source_path': str(self.source),
            'name': 'Obnovení původní geometrie', 'profile_path': profile['path'], 'profile_sha256': profile['sha256'],
            'environment': os.environ.get('OCR_ENVIRONMENT')})
        self.assertTrue(started['ok'], started)
        identifier = started['data']['run_id']
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            status = self.app.dispatch('autonomous_status', {'run_id': identifier})['data']
            if status['state'] not in ('starting', 'running'):
                break
            time.sleep(.05)
        self.assertEqual(status['state'], 'failed', status)
        failed = self.app.dispatch('geometry_status', {'run_id': identifier})['data']
        self.assertEqual(failed['turns'][-1]['state'], 'completed')
        detail = self.app.dispatch('select_run', {'run_id': identifier})['data']
        work = self.root / detail['artifacts']['workspace']['path']
        (work / 'geometry-checkpoint.json').rmdir()
        protocols = {p: p.read_bytes() for p in (work / 'application/geometry-attempts').rglob('protocol.jsonl')}
        recovered = self.app.dispatch('recover_geometry', {'run_id': identifier, 'attempt_id': failed['attempt_id']})
        self.assertTrue(recovered['ok'], recovered)
        self.assertEqual(recovered['data']['new_ai_turns'], 0)
        result = self.app.dispatch('phase_preview', {'run_id': identifier, 'phase': 'geometry', 'page': 1})
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['data']['state'], 'available', result['data']['message'])
        self.assertEqual(result['data']['overlays'][0]['text'], 'AXC')
        self.assertEqual({p: p.read_bytes() for p in protocols}, protocols)


class GeometryPreviewMigrationTests(unittest.TestCase):
    setUp = export_scenarios.AutonomousExportTests.setUp

    def test_reviewed_prior_generation_remains_verifiable_only_with_its_exact_archived_adapter(self):
        self.app.close()
        previous = ROOT / 'tests/fixtures/geometry-adapter-before-phase-previews.py'
        self.assertEqual(hashlib.sha256(previous.read_bytes()).hexdigest(),
            'ce6d912f9bddc7d58a61e8ce1b37fb733a2768a3bdb6c7637e76734281b4d2ae')
        old_prefix = self.directory / 'prior-native-generation'
        shutil.copytree(ROOT / 'tools', old_prefix / 'tools', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copytree(ROOT / 'native', old_prefix / 'native', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copyfile(previous, old_prefix / 'tools/ocr_project_geometry.py')
        # Keep the prior helper's calling contract as well. The current native
        # validator can require trusted activity names without rewriting old code.
        shutil.copyfile(ROOT / 'tests/fixtures/visual-evidence-before-activity-overrides.py',
            old_prefix / 'tools/ocr_visual_evidence.py')
        shutil.copyfile(ROOT / 'tests/fixtures/output-review-before-activity-overrides.py',
            old_prefix / 'tools/ocr_project_output_review.py')
        from app.service import Application
        self.app = Application(self.root, process_command=[sys.executable, str(old_prefix / 'tools/ocr_projects.py')],
            codex_runtime=self.runtime, context_runtime=self.context)
        profile = self.app.dispatch('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})['data']
        started = self.app.dispatch('start_autonomous', {'source_path': str(self.source), 'name': 'Původní generátor geometrie',
            'profile_path': profile['path'], 'profile_sha256': profile['sha256'], 'defer_corrections': True,
            'environment': os.environ.get('OCR_ENVIRONMENT')})
        self.assertTrue(started['ok'], started)
        identifier = started['data']['run_id']
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            status = self.app.dispatch('autonomous_status', {'run_id': identifier})['data']
            if status['state'] not in ('starting', 'running'):
                break
            time.sleep(.05)
        self.assertEqual(status['state'], 'completed', status)
        detail = self.app.dispatch('select_run', {'run_id': identifier})['data']
        work = self.root / detail['artifacts']['workspace']['path']
        adapter = work / 'geometry-code-snapshots' / (hashlib.sha256(previous.read_bytes()).hexdigest() + '.py')
        frozen = {path: path.read_bytes() for path in [adapter, work / 'geometry-preparation.json', work / 'geometry-checkpoint.json']}
        self.app.close()
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        current = self.app.dispatch('geometry_status', {'run_id': identifier})
        self.assertTrue(current['ok'], current)
        self.assertTrue(current['data']['geometry_complete'], current['data'])
        self.assertEqual({path: path.read_bytes() for path in frozen}, frozen)
        missing = self.app.dispatch('phase_preview', {'run_id': identifier, 'phase': 'geometry', 'page': 1})
        self.assertEqual(missing['data']['state'], 'historical_missing')
        adapter.write_bytes(adapter.read_bytes() + b'\n# changed original evidence\n')
        rejected = self.app.dispatch('geometry_status', {'run_id': identifier})
        self.assertTrue(rejected['ok'], rejected)
        self.assertFalse(rejected['data']['geometry_complete'])
