"""Public correction scenarios with native exports and an explicitly controlled peer."""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
import sys
import time
import unittest

import test_webui_export as export_scenarios
ROOT = export_scenarios.ROOT


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        export_scenarios.AutonomousExportTests.setUp(self)
        destination = ROOT / '.scratch/ticket-18-proof' / self._testMethodName
        def preserve():
            self.app.close()
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(self.directory, destination)
        self.addCleanup(preserve)

    def start(self, mode='repair', *, defer=True):
        from app.service import Application
        self.app.close()
        fixture = ROOT / 'tests/corrections_app_server_fixture.py'
        wrapper = self.directory / ('peer-' + mode + '.py')
        wrapper.write_text('import sys,runpy\nsys.argv.insert(1,' + repr(mode) + ')\nrunpy.run_path(' + repr(str(fixture)) + ',run_name="__main__")\n')
        self.app = Application(self.root, codex_runtime={**self.runtime,
            'command': [sys.executable, '-B', str(wrapper)],
            'files': [*self.runtime['files'], {'path': str(fixture),
                'sha256': hashlib.sha256(fixture.read_bytes()).hexdigest()}, {'path': str(wrapper),
                'sha256': hashlib.sha256(wrapper.read_bytes()).hexdigest()}]}, context_runtime=self.context)
        profile = self.app.dispatch('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})['data']
        response = self.app.dispatch('start_autonomous', {'source_path': str(self.source), 'name': 'Correction scenario',
            'profile_path': profile['path'], 'profile_sha256': profile['sha256'],
            'defer_corrections': defer,
            'environment': os.environ.get('OCR_ENVIRONMENT')})
        self.assertTrue(response['ok'], response)
        self.identifier = response['data']['run_id']
        state = self.wait('autonomous_status', 150)
        self.assertEqual(state['state'], 'completed', state)
        self.detail = self.app.dispatch('select_run', {'run_id': self.identifier})['data']
        self.work = self.root / self.detail['artifacts']['workspace']['path']

    def wait(self, operation, seconds=90):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            response = self.app.dispatch(operation, {'run_id': self.identifier})
            self.assertTrue(response['ok'], response)
            if response['data']['state'] not in ('starting', 'running'):
                return response['data']
            time.sleep(.05)
        self.fail(operation + ' did not settle')

    def correction(self, **extra):
        manifest = json.loads((self.work / 'output-manifest.json').read_text())
        response = self.app.dispatch('start_corrections', {'run_id': self.identifier,
            'expected_iteration_id': manifest['iteration_id'],
            'expected_validation_sha256': hashlib.sha256((self.work / 'checks/run-validation.json').read_bytes()).hexdigest(),
            'environment': os.environ.get('OCR_ENVIRONMENT'), **extra})
        self.assertTrue(response['ok'], response)
        return self.wait('correction_status')

    def test_targeted_source_patch_creates_new_iteration_with_original_reports_and_expectations(self):
        self.start()
        old_manifest = json.loads((self.work / 'output-manifest.json').read_text())
        old_pdf = Path(old_manifest['pdf']).read_bytes()
        old_report = (self.work / 'checks/geometry-samples.json').read_bytes()
        old_visual = (self.work / 'checks/visual-review.json').read_bytes()
        frozen = {str(p): p.read_bytes() for p in [self.source, self.work / 'samples.json',
            self.work / 'geometry-source-samples.json', self.root / self.detail['artifacts']['profile_snapshot']['path'],
            *list((self.work / 'application/reading-attempts').rglob('protocol.jsonl'))]}
        self.assertIn('AXC', Path(old_manifest['txt']).read_text())
        status = self.correction()
        self.assertEqual(status['state'], 'completed', status)
        self.assertEqual(status['cycles_used'], 1, status)
        self.assertEqual(status['stop_reason'], 'awaiting_input', status)
        self.assertEqual(status['validation'], 'ready_with_open_items')
        self.assertEqual(status['acceptance'], 'not_recorded')
        new_manifest = json.loads((self.work / 'output-manifest.json').read_text())
        self.assertNotEqual(new_manifest['iteration_id'], old_manifest['iteration_id'])
        self.assertEqual(Path(new_manifest['txt']).read_text(), 'ABC\n\n\nDEF\n')
        self.assertEqual(Path(old_manifest['pdf']).read_bytes(), old_pdf)
        cycle = status['cycles'][0]
        archived = self.work / cycle['previous_snapshot']
        self.assertEqual((archived / 'checks/geometry-samples.json').read_bytes(), old_report)
        self.assertEqual((archived / 'checks/visual-review.json').read_bytes(), old_visual)
        self.assertTrue((archived / 'output-review-publication.json').is_file())
        for name, data in frozen.items():
            self.assertEqual(Path(name).read_bytes(), data)
        results = self.app.dispatch('correction_history', {'run_id': self.identifier})
        self.assertTrue(results['ok'], results)
        self.assertEqual(len(results['data']['cycles']), 1)
        self.assertTrue(any(a['path'].endswith('/snapshot.json') for a in results['data']['artifacts']))
        proposal = json.loads((self.work / cycle['proposal']).read_text())
        self.assertTrue(all(i.startswith('sample/') for i in proposal['target_finding_ids']))
        self.assertEqual(proposal['patch']['lines'][0]['line']['text'], 'ABC')
        self.assertTrue(all('corrections/' in i['path'] for i in proposal['images_examined']))
        corrected_geometry = json.loads((self.work / 'geometry-checkpoint.json').read_text())
        examination = json.loads(Path(corrected_geometry['evidence']['proposal']['path']).read_text())
        self.assertEqual([r['id'] for r in examination['lines']], ['line-1'])
        self.assertEqual([r['id'] for r in examination['samples']], ['sample-1'])
        self.assertFalse(any(i['path'] == 'raster/page-2.png' for i in examination['images_examined']))
        self.assertEqual(corrected_geometry['correction_scope']['unchanged_line_ids'], ['line-2'])
        self.assertEqual(corrected_geometry['correction_scope']['previous_snapshot'], cycle['previous_snapshot'])
        plan = json.loads((self.work / cycle['plan']).read_text())
        self.assertEqual(plan['source_crops'][0]['line_id'], 'line-1')
        self.assertEqual(plan['source_crops'][0]['bbox'], [0, 0, 100, 40])
        self.assertTrue(any(image['kind'] == 'geometry_overlay' for image in plan['diagnostic_images']))
        metrics = self.app.dispatch('run_metrics', {'run_id': self.identifier})
        self.assertTrue(metrics['ok'], metrics)
        self.assertEqual(len([s for s in metrics['data']['steps'] if s['operation'] == 'corrections']), 1)
        geometry = self.app.dispatch('geometry_status', {'run_id': self.identifier})
        self.assertTrue(geometry['ok'], geometry)
        self.assertEqual([r['id'] for r in geometry['data']['observations']['lines']], ['line-1'])
        self.assertTrue(any(r['id'] == 'line-2' and r['kind'] == 'lines' for r in geometry['data']['historical_observations']))

    def test_same_sample_failure_stops_after_one_attempt_and_reload_cannot_reset_budget(self):
        self.start('repeated')
        status = self.correction()
        self.assertEqual(status['cycles_used'], 1, status)
        self.assertEqual(status['stop_reason'], 'repeated_failure', status)
        self.assertEqual(status['validation'], 'ready_with_open_items')
        self.assertTrue(any(r['id'] == 'sample/sample-1/mupdf' for r in status['open_items']))
        self.app.close()
        from app.service import Application
        self.app = Application(self.root, codex_runtime=self.app.corrections.runtime, context_runtime=self.context)
        reloaded = self.app.dispatch('correction_status', {'run_id': self.identifier})['data']
        self.assertEqual(reloaded['cycles_used'], 1)
        self.assertEqual(reloaded['stop_reason'], 'repeated_failure')
        manifest = json.loads((self.work / 'output-manifest.json').read_text())
        denied = self.app.dispatch('start_corrections', {'run_id': self.identifier,
            'expected_iteration_id': manifest['iteration_id'],
            'expected_validation_sha256': hashlib.sha256((self.work / 'checks/run-validation.json').read_bytes()).hexdigest()})
        self.assertFalse(denied['ok'], denied)
        self.assertEqual(denied['error']['code'], 'correction_stopped')
        self.assertEqual(len(list((self.work / 'application/correction-attempts').rglob('repair_*/request.json'))), 1)

    def test_full_autonomous_action_follows_export_with_targeted_corrections(self):
        self.start(defer=False)
        result = self.app.dispatch('correction_status', {'run_id': self.identifier})['data']
        self.assertEqual(result['cycles_used'], 1, result)
        self.assertEqual(result['stop_reason'], 'awaiting_input', result)
        manifest = json.loads((self.work / 'output-manifest.json').read_text())
        self.assertEqual(Path(manifest['txt']).read_text(), 'ABC\n\n\nDEF\n')
        self.assertEqual(len(list((self.work / 'application/reading-attempts').glob('*/attempt.json'))), 1)

    def test_three_distinct_failures_exhaust_the_durable_budget_without_acceptance(self):
        self.start('limit')
        status = self.correction()
        self.assertEqual(status['cycles_used'], 3, status)
        self.assertEqual(status['cycles_remaining'], 0)
        self.assertEqual(status['stop_reason'], 'limit_reached', status)
        self.assertEqual(status['validation'], 'ready_with_open_items')
        self.assertEqual(status['acceptance'], 'not_recorded')
        self.assertEqual([c['index'] for c in status['cycles']], [1, 2, 3])
        self.assertEqual(len({c['source_iteration_id'] for c in status['cycles']}), 3)
        self.assertEqual(len(list((self.work / 'application/correction-attempts').rglob('repair_*/request.json'))), 3)
        for cycle in status['cycles']:
            self.assertTrue((self.work / cycle['outcome']).is_file())
            self.assertEqual(hashlib.sha256((self.work / cycle['outcome']).read_bytes()).hexdigest(), cycle['outcome_sha256'])
        before = (self.work / 'application/corrections/ledger.json').read_bytes()
        from app.service import Application
        other = Application(self.root, codex_runtime=self.app.corrections.runtime, context_runtime=self.context)
        self.addCleanup(other.close)
        manifest = json.loads((self.work / 'output-manifest.json').read_text())
        denied = other.dispatch('start_corrections', {'run_id': self.identifier,
            'expected_iteration_id': manifest['iteration_id'],
            'expected_validation_sha256': hashlib.sha256((self.work / 'checks/run-validation.json').read_bytes()).hexdigest()})
        self.assertFalse(denied['ok'], denied)
        self.assertEqual(denied['error']['code'], 'correction_stopped')
        self.assertEqual((self.work / 'application/corrections/ledger.json').read_bytes(), before)

    def test_invalid_whole_review_patch_keeps_the_last_valid_export_and_all_frozen_reports(self):
        self.start('invalid')
        manifest = json.loads((self.work / 'output-manifest.json').read_text())
        protected = [self.work / 'review.json', self.work / 'output-manifest.json', self.work / 'samples.json',
            self.work / 'geometry-source-samples.json', self.work / 'geometry-checkpoint.json',
            self.work / 'output-review-publication.json', Path(manifest['pdf']), Path(manifest['txt']),
            *[p for p in (self.work / 'checks').rglob('*') if p.is_file()]]
        before = {str(p): p.read_bytes() for p in protected}
        status = self.correction()
        self.assertEqual(status['state'], 'failed', status)
        self.assertEqual(status['cycles_used'], 1)
        self.assertEqual(status['stop_reason'], 'invalid_patch')
        self.assertEqual(status['validation'], 'ready_with_open_items')
        self.assertEqual(status['acceptance'], 'not_recorded')
        self.assertFalse(list((self.work / 'iterations').glob('*/snapshot.json')))
        for name, data in before.items():
            self.assertEqual(Path(name).read_bytes(), data, name)
        output = self.app.dispatch('output_results', {'run_id': self.identifier})
        self.assertTrue(output['ok'], output)
        self.assertEqual(output['data']['report_provenance']['status'], 'original_turn_verified')
        denied = self.app.dispatch('open_correction_artifact', {'run_id': self.identifier,
            'path': '../../private.pdf', 'sha256': '0' * 64})
        self.assertFalse(denied['ok'], denied)

    def test_stale_start_consumes_nothing_and_original_noop_is_one_settled_attempt(self):
        self.start('noop')
        original = (self.work / 'review.json').read_bytes()
        manifest = (self.work / 'output-manifest.json').read_bytes()
        stale = self.app.dispatch('start_corrections', {'run_id': self.identifier,
            'expected_iteration_id': 'foreign-iteration', 'expected_validation_sha256': '0' * 64})
        self.assertFalse(stale['ok'], stale)
        self.assertFalse((self.work / 'application/corrections/ledger.json').exists())
        self.assertFalse(list((self.work / 'application/correction-attempts').glob('*/attempt.json')))
        status = self.correction()
        self.assertEqual(status['state'], 'failed', status)
        self.assertEqual(status['cycles_used'], 1)
        self.assertEqual(status['stop_reason'], 'no_valid_change', status)
        self.assertEqual(status['validation'], 'ready_with_open_items')
        self.assertEqual((self.work / 'review.json').read_bytes(), original)
        self.assertEqual((self.work / 'output-manifest.json').read_bytes(), manifest)
        self.assertFalse(list((self.work / 'iterations').glob('*/snapshot.json')))
        ledger_before = (self.work / 'application/corrections/ledger.json').read_bytes()
        invalid = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/ocr_projects.py'),
            '--root', str(self.root), '--json', 'settle-correction', self.identifier,
            '--cycle-id', 'foreign-cycle'], capture_output=True)
        self.assertEqual(invalid.returncode, 1)
        self.assertEqual(json.loads(invalid.stdout)['error']['code'], 'correction_invalid')
        self.assertEqual((self.work / 'application/corrections/ledger.json').read_bytes(), ledger_before)

    def test_publisher_error_registry_cannot_be_editorially_rewritten_by_a_native_valid_patch(self):
        self.start('publisher')
        original = (self.work / 'review.json').read_bytes()
        status = self.correction()
        self.assertEqual(status['state'], 'failed', status)
        self.assertEqual(status['stop_reason'], 'invalid_patch', status)
        self.assertEqual((self.work / 'review.json').read_bytes(), original)
        self.assertEqual(status['validation'], 'ready_with_open_items')
        self.assertFalse(list((self.work / 'iterations').glob('*/snapshot.json')))


if __name__ == '__main__':
    unittest.main()
