"""Per-activity preferences at the established public application boundary."""
import json
import hashlib
import os
import time
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.service import Application


class ActivityPreferencesTests(unittest.TestCase):
    def test_overrides_copy_independently_clear_to_common_and_freeze_in_each_run(self):
        with tempfile.TemporaryDirectory(prefix='Výjimky AI ') as directory:
            directory = Path(directory)
            root = directory / 'evidence'
            app = Application(root)
            self.addCleanup(app.close)
            def request(operation, payload=None):
                response = app.dispatch(operation, payload)
                self.assertTrue(response['ok'], response)
                return response['data']
            common = {'model': 'common-model', 'reasoning_effort': 'medium'}
            reading = {'model': 'reading-model', 'reasoning_effort': 'high'}
            request('set_global_preferences', {**common, 'overrides': {'reading': reading}})
            source = directory / 'listopad.pdf'
            source.write_bytes(b'%PDF-1.4\nactivity profile fixture\n%%EOF\n')
            edition = request('import_sources', {'path': str(source)})['editions'][0]['edition_id']
            project = request('project_preferences', {'edition_id': edition})
            self.assertEqual(project['preferences']['overrides'], {'reading': reading})
            self.assertEqual(project['effective']['reading'], reading)
            self.assertEqual(project['effective']['geometry'], common)
            profile = request('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})
            payload = {'edition_id': edition, 'profile_path': profile['path'], 'profile_sha256': profile['sha256']}
            first = request('create_run', {**payload, 'name': 'S výjimkou'})
            request('set_global_preferences', {**common, 'overrides': {}})
            self.assertEqual(request('project_preferences', {'edition_id': edition})['effective']['reading'], reading)
            request('set_project_preferences', {'edition_id': edition, **common, 'overrides': {}})
            self.assertEqual(request('project_preferences', {'edition_id': edition})['effective']['reading'], common)
            second = request('create_run', {**payload, 'name': 'Bez výjimky'})
            self.assertEqual(first['run']['profile']['parameters']['activity_overrides'], {'reading': reading})
            self.assertNotIn('activity_overrides', second['run']['profile']['parameters'])
            app.close()
            app = Application(root)
            self.addCleanup(app.close)
            self.assertEqual(request('select_run', {'run_id': first['project']['run_id']})['run'], first['run'])
            self.assertEqual(request('project_preferences', {'edition_id': edition})['effective']['reading'], common)


    def test_unavailable_override_and_malformed_overrides_never_fall_back_to_common(self):
        with tempfile.TemporaryDirectory(prefix='Neplatná výjimka ') as directory:
            directory = Path(directory)
            fixture = ROOT / 'tests/codex_app_server_fixture.py'
            runtime = {'kind': 'controlled_process_fixture', 'version': 'activity-catalog',
                'command': [sys.executable, str(fixture), 'success'],
                'files': [{'path': str(fixture), 'sha256': hashlib.sha256(fixture.read_bytes()).hexdigest()}]}
            app = Application(directory / 'evidence', codex_runtime=runtime)
            self.addCleanup(app.close)
            pair = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high'}
            for overrides in ({'unknown_activity': pair}, {'reading': None},
                              {'reading': {'model': 'missing-effort'}},
                              {'reading': {**pair, 'reasoning_effort': 'silently-default'}}):
                rejected = app.dispatch('set_global_preferences', {**pair, 'overrides': overrides})
                self.assertFalse(rejected['ok'], rejected)
                self.assertEqual(rejected['error']['code'], 'preferences_invalid')
            self.assertTrue(app.dispatch('start_model_capabilities')['ok'])
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                catalog = app.dispatch('model_capabilities')['data']
                if catalog['state'] not in ('starting', 'running'):
                    break
                time.sleep(.02)
            self.assertEqual(catalog['state'], 'completed', catalog)
            app.dispatch('set_global_preferences', {**pair, 'overrides': {'geometry': {
                'model': 'unavailable-model', 'reasoning_effort': 'high'}}})
            source = directory / 'source.pdf'
            source.write_bytes(b'%PDF-1.4\nunavailable activity fixture\n%%EOF\n')
            edition = app.dispatch('import_sources', {'path': str(source)})['data']['editions'][0]['edition_id']
            saved = app.dispatch('project_preferences', {'edition_id': edition})['data']
            self.assertEqual(saved['effective']['geometry']['model'], 'unavailable-model')
            self.assertEqual(saved['activity_availability']['geometry']['state'], 'unavailable')
            profile = app.dispatch('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})['data']
            rejected = app.dispatch('create_run', {'edition_id': edition, 'name': 'Nedostupná geometrie',
                'profile_path': profile['path'], 'profile_sha256': profile['sha256']})
            self.assertFalse(rejected['ok'], rejected)
            self.assertEqual(rejected['error']['code'], 'model_capability_unavailable')
            self.assertEqual(len(app.dispatch('projects')['data']['editions'][0]['runs']), 1)


class ActivityWorkflowTests(unittest.TestCase):
    PAIRS = {
        'reading': {'model': 'read-model', 'reasoning_effort': 'medium'},
        'geometry': {'model': 'geometry-model', 'reasoning_effort': 'low'},
        'final_check': {'model': 'check-model', 'reasoning_effort': 'high'},
        'repair': {'model': 'repair-model', 'reasoning_effort': 'xhigh'},
    }

    def setUp(self):
        from test_webui_export import AutonomousExportTests
        AutonomousExportTests.setUp(self)
        fixtures = self.directory / 'activity-fixtures'
        fixtures.mkdir()
        files = []
        for name in ('autonomous_app_server_fixture.py', 'codex_app_server_fixture.py',
                     'context_app_server_fixture.py', 'reading_app_server_fixture.py',
                     'geometry_app_server_fixture.py', 'corrections_app_server_fixture.py'):
            source = (ROOT / 'tests' / name).read_text()
            if name in ('codex_app_server_fixture.py', 'context_app_server_fixture.py', 'reading_app_server_fixture.py'):
                source = source.replace("'gpt-6.1-sol'", "'read-model'").replace("'high'", "'medium'")
            elif name == 'geometry_app_server_fixture.py':
                source = source.replace("'model': 'gpt-6.1-sol', 'reasoningEffort': 'high'",
                    "'model': params['model'], 'reasoningEffort': params['config']['model_reasoning_effort']")
                source = source.replace("        prompt = params['input'][0]['text']", "        prompt = params['input'][0]['text']\n" +
                    "        pair = ('check-model', 'high') if 'OUTPUT_PACKET\\n' in prompt else ('repair-model', 'xhigh') if 'CORRECTION_PACKET\\n' in prompt else ('geometry-model', 'low')\n" +
                    "        assert (params['model'], params['effort']) == pair, (params, pair)")
                catalog = {'data': [{'model': value['model'], 'inputModalities': ['text', 'image'],
                    'supportedReasoningEfforts': [{'reasoningEffort': value['reasoning_effort']}]} for value in self.PAIRS.values()], 'nextCursor': None}
                source = source.replace("    elif method == 'thread/start':", "    elif method == 'model/list':\n        result = " + repr(catalog) + "\n    elif method == 'thread/start':")
            target = fixtures / name
            target.write_text(source)
            files.append({'path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
        self.app.close()
        self.app = Application(self.root, codex_runtime={**self.runtime,
            'command': [sys.executable, '-B', str(fixtures / 'corrections_app_server_fixture.py'), 'repair'],
            'files': files}, context_runtime=self.context)

    def wait(self, operation, identifier):
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

    def test_each_physical_ai_turn_uses_its_frozen_activity_override(self):
        self.assertTrue(self.app.dispatch('start_model_capabilities')['ok'])
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            catalog = self.app.dispatch('model_capabilities')['data']
            if catalog['state'] not in ('starting', 'running'):
                break
            time.sleep(.02)
        self.assertEqual(catalog['state'], 'completed', catalog)
        self.assertTrue(self.app.dispatch('set_global_preferences', {'model': 'unused-common',
            'reasoning_effort': 'high', 'overrides': self.PAIRS})['ok'])
        profile = self.app.dispatch('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})['data']
        started = self.app.dispatch('start_autonomous', {'source_path': str(self.source), 'name': 'Výjimky činností',
            'profile_path': profile['path'], 'profile_sha256': profile['sha256'],
            'defer_corrections': True, 'environment': os.environ.get('OCR_ENVIRONMENT')})
        self.assertTrue(started['ok'], started)
        identifier = started['data']['run_id']
        self.wait('autonomous_status', identifier)
        detail = self.app.dispatch('select_run', {'run_id': identifier})['data']
        work = self.root / detail['artifacts']['workspace']['path']
        self.assertTrue(self.app.dispatch('set_project_preferences', {'edition_id': detail['edition_id'],
            'model': 'later-common', 'reasoning_effort': 'low', 'overrides': {}})['ok'])
        manifest = json.loads((work / 'output-manifest.json').read_text())
        repaired = self.app.dispatch('start_corrections', {'run_id': identifier,
            'expected_iteration_id': manifest['iteration_id'],
            'expected_validation_sha256': hashlib.sha256((work / 'checks/run-validation.json').read_bytes()).hexdigest(),
            'environment': os.environ.get('OCR_ENVIRONMENT')})
        self.assertTrue(repaired['ok'], repaired)
        self.wait('correction_status', identifier)
        activities = set()
        for protocol in (work / 'application').glob('*-attempts/*/protocol.jsonl'):
            namespace = protocol.parents[1].name
            for raw in protocol.read_text().splitlines():
                message = json.loads(raw)['message']
                if message.get('method') != 'turn/start':
                    continue
                params = message['params']
                prompt = params['input'][0]['text']
                if namespace in ('codex-attempts', 'context-attempts', 'reading-attempts'):
                    activity = 'reading'
                elif 'OUTPUT_PACKET\n' in prompt:
                    activity = 'final_check'
                elif 'CORRECTION_PACKET\n' in prompt:
                    activity = 'repair'
                else:
                    activity = 'geometry'
                activities.add(activity)
                self.assertEqual(params['model'], self.PAIRS[activity]['model'])
                self.assertEqual(params['effort'], self.PAIRS[activity]['reasoning_effort'])
        self.assertEqual(activities, set(self.PAIRS))
        metrics = self.app.dispatch('run_metrics', {'run_id': identifier})
        self.assertTrue(metrics['ok'], metrics)
        mixed = next(step for step in metrics['data']['steps'] if step.get('operation') == 'corrections')
        self.assertIsNone(mixed['model'])
        self.assertIsNone(mixed['cost']['usd'])
        self.assertEqual({item['model'] for item in mixed['model_settings']}, {'repair-model', 'geometry-model'})



if __name__ == '__main__':
    unittest.main()
