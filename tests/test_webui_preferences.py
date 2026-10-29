"""Persistent model preferences through the public application request seam."""
import json
import base64
import hashlib
import time
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.service import Application


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='OCR předvolby ')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / 'evidence'
        self.app = Application(self.root)
        self.addCleanup(lambda: self.app.close())

    def source(self, name, content):
        path = self.directory / name
        path.write_bytes(b'%PDF-1.4\n' + content + b'\n%%EOF\n')
        return path

    def request(self, operation, payload=None):
        response = self.app.dispatch(operation, payload)
        self.assertTrue(response['ok'], response)
        return response['data']

    def test_global_copy_project_adoption_and_frozen_runs_survive_restart(self):
        self.request('set_global_preferences', {'model': 'selected-model', 'reasoning_effort': 'medium'})
        first = self.source('červen.pdf', b'first')
        edition = self.request('import_sources', {'path': str(first)})['editions'][0]['edition_id']
        self.assertEqual(self.request('project_preferences', {'edition_id': edition})['preferences'],
                         {'model': 'selected-model', 'reasoning_effort': 'medium'})
        profile = self.request('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})
        run = self.request('create_run', {'edition_id': edition, 'name': 'Původní',
            'profile_path': profile['path'], 'profile_sha256': profile['sha256']})
        old_id = run['project']['run_id']
        self.assertEqual(run['run']['profile']['parameters']['model'], 'selected-model')
        self.assertEqual(run['run']['profile']['parameters']['reasoning_effort'], 'medium')
        self.request('set_global_preferences', {'model': 'new-default', 'reasoning_effort': 'low'})
        self.assertEqual(self.request('project_preferences', {'edition_id': edition})['preferences']['model'], 'selected-model')
        self.request('set_project_preferences', {'edition_id': edition, 'model': 'project-model', 'reasoning_effort': 'high'})
        self.app.close()
        self.app = Application(self.root)
        self.assertEqual(self.request('global_preferences')['preferences']['model'], 'new-default')
        self.assertEqual(self.request('project_preferences', {'edition_id': edition})['preferences']['model'], 'project-model')
        self.request('adopt_global_preferences', {'edition_id': edition})
        newer = self.request('create_run', {'edition_id': edition, 'name': 'Nový',
            'profile_path': profile['path'], 'profile_sha256': profile['sha256']})
        self.assertEqual(newer['run']['profile']['parameters']['model'], 'new-default')
        self.assertEqual(self.request('select_run', {'run_id': old_id})['run'], run['run'])


    def test_runtime_catalog_preserves_unavailable_saved_choice_and_refuses_new_run(self):
        fixture = ROOT / 'tests/codex_app_server_fixture.py'
        self.app.close()
        runtime = {'kind': 'controlled_process_fixture', 'version': 'catalog-fixture',
            'command': [sys.executable, str(fixture), 'success'],
            'files': [{'path': str(fixture), 'sha256': hashlib.sha256(fixture.read_bytes()).hexdigest()}]}
        self.app = Application(self.root, codex_runtime=runtime)
        self.request('start_model_capabilities')
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            catalog = self.request('model_capabilities')
            if catalog['state'] not in ('starting', 'running'):
                break
            time.sleep(.02)
        self.assertEqual(catalog['state'], 'completed', catalog)
        self.assertEqual(catalog['models'][0]['model'], 'gpt-6.1-sol')
        self.request('set_global_preferences', {'model': 'unavailable-choice', 'reasoning_effort': 'medium'})
        source = self.source('prosinec.pdf', b'unavailable')
        edition = self.request('import_sources', {'path': str(source)})['editions'][0]['edition_id']
        saved = self.request('project_preferences', {'edition_id': edition})
        self.assertEqual(saved['preferences']['model'], 'unavailable-choice')
        self.assertEqual(saved['availability']['state'], 'unavailable')
        profile = self.request('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})
        rejected = self.app.dispatch('create_run', {'edition_id': edition, 'name': 'Nedostupný',
            'profile_path': profile['path'], 'profile_sha256': profile['sha256']})
        self.assertFalse(rejected['ok'], rejected)
        self.assertEqual(rejected['error']['code'], 'model_capability_unavailable')
        self.assertEqual(len(self.request('projects')['editions'][0]['runs']), 1)

    def test_selected_model_reaches_the_original_diagnostic_request_without_fallback(self):
        fixture = self.directory / 'selected_peer.py'
        fixture.write_text((ROOT / 'tests/codex_app_server_fixture.py').read_text().replace(
            "'gpt-6.1-sol'", "'selected-model'").replace("'high'", "'medium'"))
        self.app.close()
        runtime = {'kind': 'controlled_process_fixture', 'version': 'preferences-fixture',
            'command': [sys.executable, str(fixture), 'success'],
            'files': [{'path': str(fixture), 'sha256': hashlib.sha256(fixture.read_bytes()).hexdigest()}]}
        self.app = Application(self.root, codex_runtime=runtime)
        self.request('set_global_preferences', {'model': 'selected-model', 'reasoning_effort': 'medium'})
        source = self.source('září.pdf', b'parameter contract')
        edition = self.request('import_sources', {'path': str(source)})['editions'][0]['edition_id']
        profile = self.request('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})
        run = self.request('create_run', {'edition_id': edition, 'name': 'Model',
            'profile_path': profile['path'], 'profile_sha256': profile['sha256']})
        image = self.directory / 'source.png'
        image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aR1sAAAAASUVORK5CYII='))
        identifier = run['project']['run_id']
        self.request('start_model_diagnostic', {'run_id': identifier, 'image_path': str(image)})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = self.request('model_diagnostic_status', {'run_id': identifier})
            if status['state'] not in ('starting', 'running'):
                break
            time.sleep(.02)
        self.assertEqual(status['state'], 'completed', status)
        self.assertEqual(status['requested'], {'model': 'selected-model', 'reasoning_effort': 'medium'})
        self.assertEqual(status['effective']['model'], 'selected-model')
        self.assertEqual(status['effective']['reasoning_effort'], 'medium')


class SelectedWorkflowTests(unittest.TestCase):
    def setUp(self):
        from test_webui_export import AutonomousExportTests
        AutonomousExportTests.setUp(self)
        fixtures = self.directory / 'selected-fixtures'
        fixtures.mkdir()
        files = []
        for name in ('autonomous_app_server_fixture.py', 'codex_app_server_fixture.py',
                     'context_app_server_fixture.py', 'reading_app_server_fixture.py',
                     'geometry_app_server_fixture.py', 'corrections_app_server_fixture.py'):
            target = fixtures / name
            target.write_text((ROOT / 'tests' / name).read_text().replace(
                "'gpt-6.1-sol'", "'selected-model'").replace("'high'", "'medium'"))
            files.append({'path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
        self.app.close()
        self.app = Application(self.root, codex_runtime={**self.runtime,
            'command': [sys.executable, '-B', str(fixtures / 'corrections_app_server_fixture.py'), 'repair'],
            'files': files}, context_runtime=self.context)

    def test_every_ai_phase_uses_the_frozen_common_pair_including_targeted_repair(self):
        self.assertTrue(self.app.dispatch('set_global_preferences', {
            'model': 'selected-model', 'reasoning_effort': 'medium'})['ok'])
        profile = self.app.dispatch('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})['data']
        started = self.app.dispatch('start_autonomous', {'source_path': str(self.source), 'name': 'Selected model',
            'profile_path': profile['path'], 'profile_sha256': profile['sha256'],
            'defer_corrections': True, 'environment': os.environ.get('OCR_ENVIRONMENT')})
        self.assertTrue(started['ok'], started)
        identifier = started['data']['run_id']
        def wait(operation):
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                response = self.app.dispatch(operation, {'run_id': identifier})
                self.assertTrue(response['ok'], response)
                status = response['data']
                if status['state'] not in ('starting', 'running'):
                    self.assertEqual(status['state'], 'completed', status)
                    return status
                time.sleep(.05)
            self.fail(operation + ' timed out')
        wait('autonomous_status')
        detail = self.app.dispatch('select_run', {'run_id': identifier})['data']
        work = self.root / detail['artifacts']['workspace']['path']
        # Later preference changes must never alter the saved run or repair.
        self.assertTrue(self.app.dispatch('set_project_preferences', {'edition_id': detail['edition_id'],
            'model': 'later-model', 'reasoning_effort': 'low'})['ok'])
        manifest = json.loads((work / 'output-manifest.json').read_text())
        repaired = self.app.dispatch('start_corrections', {'run_id': identifier,
            'expected_iteration_id': manifest['iteration_id'],
            'expected_validation_sha256': hashlib.sha256((work / 'checks/run-validation.json').read_bytes()).hexdigest(),
            'environment': os.environ.get('OCR_ENVIRONMENT')})
        self.assertTrue(repaired['ok'], repaired)
        wait('correction_status')
        namespaces = set()
        for protocol in (work / 'application').glob('*-attempts/*/protocol.jsonl'):
            for raw in protocol.read_text().splitlines():
                frame = json.loads(raw)['message']
                if frame.get('method') != 'turn/start':
                    continue
                namespaces.add(protocol.parents[1].name)
                self.assertEqual(frame['params']['model'], 'selected-model')
                self.assertEqual(frame['params']['effort'], 'medium')
        self.assertTrue({'codex-attempts', 'context-attempts', 'reading-attempts', 'geometry-attempts',
                         'output-review-attempts', 'correction-attempts'} <= namespaces, namespaces)


if __name__ == '__main__':
    unittest.main()
