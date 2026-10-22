"""Codex diagnostics through the approved public application/process seam."""
import base64
import hashlib
import json
import shutil
import os
from pathlib import Path
import sys
import signal
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.service import Application


class CodexDiagnosticTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='Codex veřejná diagnostika ')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.registry = self.directory / 'registry'
        self.image = self.directory / 'prepared.png'
        self.image.write_bytes(base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aR1sAAAAASUVORK5CYII='))
        self.app = Application(self.registry)
        source = self.directory / 'source.pdf'
        source.write_bytes(b'%PDF-1.4\ncontrolled registry input\n%%EOF\n')
        imported = self.app.dispatch('import_sources', {'path': str(source)})
        self.assertTrue(imported['ok'], imported)
        profile = self.app.dispatch('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})['data']
        created = self.app.dispatch('create_run', {'edition_id': imported['data']['editions'][0]['edition_id'],
            'name': 'Ověření obrazu', 'profile_path': profile['path'], 'profile_sha256': profile['sha256']})
        self.assertTrue(created['ok'], created)
        self.run = created['data']
        self.identifier = self.run['project']['run_id']

    def peer(self, mode='success', invalid_pin=False):
        self.app.close()
        fixture = ROOT / 'tests/codex_app_server_fixture.py'
        runtime = {'command': [sys.executable, str(fixture), mode], 'version': 'controlled-fixture-13',
                   'kind': 'controlled_process_fixture', 'files': [
                       {'path': str(fixture), 'sha256': '0' * 64 if invalid_pin else hashlib.sha256(fixture.read_bytes()).hexdigest()}]}
        self.app = Application(self.registry, codex_runtime=runtime)
        self.addCleanup(self.app.close)

    def wait(self):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            response = self.app.dispatch('model_diagnostic_status', {'run_id': self.identifier})
            self.assertTrue(response['ok'], response)
            if response['data']['state'] not in ('starting', 'running', 'awaiting_login'):
                return response['data']
            time.sleep(.02)
        self.fail('Controlled child did not reach a terminal state.')

    def test_image_attempt_preserves_exact_configuration_trace_and_usage_presence_after_restart(self):
        self.peer()
        started = self.app.dispatch('start_model_diagnostic', {'run_id': self.identifier, 'image_path': str(self.image)})
        self.assertTrue(started['ok'], started)
        result = self.wait()
        self.assertEqual(result['state'], 'completed', result)
        self.assertEqual(result['answer'], 'VISION CHILD 13')
        self.assertEqual(result['requested'], {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high'})
        self.assertEqual(result['thread_id'], 'fixture-thread-13')
        self.assertEqual(result['turn_id'], 'fixture-turn-13')
        self.assertFalse(result['autonomous_ocr_ready'])
        self.assertFalse(result['native_runtime'])
        self.assertEqual(result['image']['sha256'], hashlib.sha256(self.image.read_bytes()).hexdigest())
        self.assertEqual(len(result['usage_events']), 1)
        self.assertNotIn('cacheWriteInputTokens', result['usage_events'][0]['tokenUsage']['total'])
        self.assertNotIn('private@example.invalid', (self.registry / result['artifacts']['protocol']).read_text())
        self.app.close()
        restored = Application(self.registry)
        self.addCleanup(restored.close)
        saved = restored.dispatch('model_diagnostic_status', {'run_id': self.identifier})
        self.assertTrue(saved['ok'], saved)
        self.assertEqual(saved['data']['attempt_id'], result['attempt_id'])
        self.assertEqual(saved['data']['answer'], result['answer'])

    def test_chatgpt_login_uses_supported_flow_and_never_persists_the_browser_secret(self):
        self.peer('login')
        checked = self.app.dispatch('check_codex_account', {'run_id': self.identifier})
        self.assertTrue(checked['ok'], checked)
        status = self.wait()
        self.assertFalse(status['authenticated'])
        started = self.app.dispatch('start_codex_login', {'run_id': self.identifier})
        self.assertTrue(started['ok'], started)
        status = self.wait()
        self.assertEqual(status['state'], 'completed', status)
        self.assertTrue(status['authenticated'])
        self.assertFalse(status['combination_verified'])
        self.assertIsNone(status['turn_id'])
        trace = (self.registry / status['artifacts']['protocol']).read_text()
        self.assertIn('account/login/start', trace)
        self.assertNotIn('private-fixture-state', trace)
        self.assertNotIn('private-fixture-state', (self.registry / status['artifacts']['attempt']).read_text())

    def test_interrupted_native_turn_preserves_observed_usage_without_claiming_access_verification(self):
        self.peer('interrupted')
        self.assertTrue(self.app.dispatch('start_model_diagnostic', {
            'run_id': self.identifier, 'image_path': str(self.image)})['ok'])
        result = self.wait()
        self.assertEqual(result['state'], 'interrupted', result)
        self.assertEqual(result['error']['code'], 'codex_turn_interrupted')
        self.assertEqual(len(result['usage_events']), 1)
        self.assertFalse(result['combination_verified'])

    def test_rejection_mismatch_reroute_protocol_and_tool_failures_cannot_verify_the_combination(self):
        baseline = self.registry
        self.app.close()
        for mode, code in [('missing_account', 'chatgpt_account_required'), ('no_vision', 'model_capability_unavailable'),
                           ('wrong_effort', 'model_configuration_mismatch'), ('wrong_model', 'model_configuration_mismatch'),
                           ('rejected', 'codex_request_rejected'), ('malformed', 'codex_protocol_invalid'),
                           ('rerouted', 'model_rerouted'), ('tool_used', 'diagnostic_tool_used')]:
            with self.subTest(mode=mode):
                # Independent variants start from native setup only, before
                # any AI attempt. An unknown prior delivery stays in its root.
                self.registry = self.directory / ('registry-' + mode)
                shutil.copytree(baseline, self.registry)
                self.peer(mode)
                started = self.app.dispatch('start_model_diagnostic', {'run_id': self.identifier, 'image_path': str(self.image)})
                self.assertTrue(started['ok'], started)
                result = self.wait()
                self.assertEqual(result['state'], 'failed', result.get('error'))
                self.assertEqual(result['error']['code'], code)
                self.assertFalse(result['combination_verified'])
                if mode == 'rerouted':
                    self.assertEqual(result['reroutes'][0]['toModel'], 'gpt-6-sol')
                    self.assertEqual(len(result['usage_events']), 1)

    def test_owned_child_termination_is_durable_and_registry_cannot_switch_during_attempt(self):
        self.peer('slow')
        self.assertTrue(self.app.dispatch('start_model_diagnostic', {'run_id': self.identifier, 'image_path': str(self.image)})['ok'])
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = self.app.dispatch('model_diagnostic_status', {'run_id': self.identifier})['data']
            if status.get('submitted_at'):
                break
            time.sleep(.02)
        else:
            self.fail('Owned child did not submit its turn.')
        self.assertIsNotNone(status['process_start_ticks'])
        self.assertEqual(status['owner_pid'], os.getpid())
        refused = self.app.dispatch('open_registry', {'root': str(self.directory)})
        self.assertEqual(refused['error']['code'], 'operation_active')
        os.killpg(status['process_group'], signal.SIGKILL)
        failed = self.wait()
        self.assertEqual(failed['error']['code'], 'codex_process_terminated')
        self.assertEqual(failed['events'][-1]['type'], 'codex_attempt_failed')
        self.assertFalse(failed['combination_verified'])

    def test_changed_pinned_image_invalidates_a_saved_success(self):
        self.peer()
        self.assertTrue(self.app.dispatch('start_model_diagnostic', {'run_id': self.identifier, 'image_path': str(self.image)})['ok'])
        result = self.wait()
        (self.registry / result['image']['path']).write_bytes(b'changed')
        invalid = self.app.dispatch('model_diagnostic_status', {'run_id': self.identifier})['data']
        self.assertEqual(invalid['state'], 'invalidated')
        self.assertFalse(invalid['combination_verified'])

    def test_corrupt_saved_attempt_is_a_public_machine_error(self):
        self.peer()
        self.assertTrue(self.app.dispatch('start_model_diagnostic', {'run_id': self.identifier, 'image_path': str(self.image)})['ok'])
        result = self.wait()
        (self.registry / result['artifacts']['attempt']).write_text('{broken')
        invalid = self.app.dispatch('model_diagnostic_status', {'run_id': self.identifier})
        self.assertFalse(invalid['ok'])
        self.assertEqual(invalid['error']['code'], 'attempt_invalid')

    def test_changed_runtime_pin_is_rejected_before_starting_a_child(self):
        self.peer(invalid_pin=True)
        self.assertTrue(self.app.dispatch('start_model_diagnostic', {'run_id': self.identifier, 'image_path': str(self.image)})['ok'])
        result = self.wait()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error']['code'], 'codex_runtime_invalid')
        self.assertIsNone(result['pid'])
        self.assertIsNone(result['turn_id'])


if __name__ == '__main__':
    unittest.main()
