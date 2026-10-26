"""Context readiness via the approved public application/process boundary."""
import json
import hashlib
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.service import Application


class ContextReadinessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='Oddělený kontext ')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.registry = self.directory / 'registry'
        self.app = Application(self.registry)
        self.addCleanup(lambda: self.app.close())
        source = self.directory / 'source.pdf'
        source.write_bytes(b'%PDF-1.4\nregistry-only fixture\n%%EOF\n')
        imported = self.app.dispatch('import_sources', {'path': str(source)})['data']
        profile = self.app.dispatch('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})['data']
        created = self.app.dispatch('create_run', {'edition_id': imported['editions'][0]['edition_id'],
            'name': 'Kontext', 'profile_path': profile['path'], 'profile_sha256': profile['sha256']})
        self.identifier = created['data']['project']['run_id']

    def wait(self):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            response = self.app.dispatch('context_status', {'run_id': self.identifier})
            self.assertTrue(response['ok'], response)
            if response['data']['state'] not in ('starting', 'running'):
                return response['data']
            time.sleep(.02)
        self.fail('Context verification did not reach a terminal state.')

    def test_missing_pinned_context_resource_fails_closed_before_codex_or_ocr(self):
        self.app.close()
        self.app = Application(self.registry, context_runtime={'files': [
            {'path': str(self.directory / 'missing-node'), 'sha256': '0' * 64}]})
        started = self.app.dispatch('start_context_diagnostic', {'run_id': self.identifier})
        self.assertTrue(started['ok'], started)
        result = self.wait()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error']['code'], 'context_runtime_invalid')
        self.assertFalse(result['autonomous_ocr_ready'])
        self.assertIsNone(result['pid'])
        self.assertIsNone(result['turn_id'])

    def peer(self, mode):
        self.app.close()
        fixture = ROOT / 'tests/context_app_server_fixture.py'
        codex = {'kind': 'controlled_process_fixture', 'version': 'fixture14',
                 'command': [sys.executable, str(fixture), mode],
                 'files': [{'path': str(fixture), 'sha256': hashlib.sha256(fixture.read_bytes()).hexdigest()}]}
        context = {'kind': 'controlled_process_fixture', 'package': str(self.directory), 'node': sys.executable,
                   'files': [], 'interpreters': [], 'probe_command': [sys.executable, '-c',
                       'print(\'{"node":"fixture","sqlite_fts5":true}\')']}
        self.app = Application(self.registry, codex_runtime=codex, context_runtime=context)

    def test_untrusted_actual_hook_metadata_stops_before_any_model_turn(self):
        self.peer('untrusted')
        self.assertTrue(self.app.dispatch('start_context_diagnostic', {'run_id': self.identifier})['ok'])
        result = self.wait()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error']['code'], 'context_hook_untrusted')
        self.assertFalse(result['autonomous_ocr_ready'])
        self.assertIsNone(result['turn_id'])

    def test_missing_chatgpt_account_or_wrong_model_never_enables_context_readiness(self):
        for mode, code in [('missing_account', 'chatgpt_account_required'), ('wrong_model', 'model_configuration_mismatch')]:
            with self.subTest(mode=mode):
                # Authentication failure is a registry-wide hold, including a
                # truthfully unsubmitted request. These are independent input
                # cases, not permission to replace that original admission.
                self.app.close()
                self.registry = self.directory / ('registry-' + mode)
                self.app = Application(self.registry)
                imported = self.app.dispatch('import_sources', {'path': str(self.directory / 'source.pdf')})['data']
                profile = self.app.dispatch('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})['data']
                self.identifier = self.app.dispatch('create_run', {'edition_id': imported['editions'][0]['edition_id'],
                    'name': mode, 'profile_path': profile['path'], 'profile_sha256': profile['sha256']})['data']['project']['run_id']
                self.peer(mode)
                self.assertTrue(self.app.dispatch('start_context_diagnostic', {'run_id': self.identifier})['ok'])
                result = self.wait()
                self.assertEqual(result['state'], 'failed')
                self.assertEqual(result['error']['code'], code)
                self.assertFalse(result['context_verified'])
                self.assertFalse(result['autonomous_ocr_ready'])
                denied = self.app.dispatch('start_context_diagnostic', {'run_id': self.identifier})
                self.assertFalse(denied['ok'], denied)
                self.assertEqual(denied['error']['code'], 'reconciliation_required')

    def test_registration_and_correct_answer_without_actual_routing_never_enable_readiness(self):
        self.peer('answer_only')
        self.assertTrue(self.app.dispatch('start_context_diagnostic', {'run_id': self.identifier})['ok'])
        result = self.wait()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error']['code'], 'context_routing_unverified')
        self.assertFalse(result['context_verified'])
        self.assertFalse(result['autonomous_ocr_ready'])

    def test_completed_routing_without_actual_compaction_hooks_cannot_enable_readiness(self):
        self.peer('no_recovery')
        self.assertTrue(self.app.dispatch('start_context_diagnostic', {'run_id': self.identifier})['ok'])
        result = self.wait()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error']['code'], 'context_recovery_unverified')
        self.assertFalse(result['context_verified'])
        protocol = (self.registry / result['artifacts']['protocol']).read_text()
        self.assertTrue('thread/compact/start' in protocol, 'The public operation did not request supported compaction.')

    def test_prepared_payload_is_reviewable_and_changed_instructions_stop_before_inference(self):
        self.peer('answer_only')
        prepared = self.app.dispatch('prepare_context_diagnostic', {'run_id': self.identifier})
        self.assertTrue(prepared['ok'], prepared)
        self.assertGreater(prepared['data']['bytes'], 500_000)
        workspace = Path(prepared['data']['path']).parent
        (workspace / 'AGENTS.md').write_text('unreviewed replacement instructions')
        self.assertTrue(self.app.dispatch('start_context_diagnostic', {'run_id': self.identifier})['ok'])
        result = self.wait()
        self.assertEqual(result['error']['code'], 'context_input_changed')
        self.assertIsNone(result['pid'])

    def test_only_named_context_tools_have_explicit_application_approval(self):
        self.peer('approval_policy')
        self.assertTrue(self.app.dispatch('start_context_diagnostic', {'run_id': self.identifier})['ok'])
        result = self.wait()
        self.assertEqual(result['error']['code'], 'context_routing_unverified')
        policy = result['effective_context_config']['mcp_servers']['context_mode']
        self.assertEqual(set(policy['tools']), {'ctx_execute', 'ctx_execute_file', 'ctx_batch_execute', 'ctx_index', 'ctx_search', 'ctx_stats'})
        self.assertNotIn('ctx_upgrade', policy['enabled_tools'])

    def test_protocol_claims_without_real_run_local_knowledge_and_session_stores_fail_closed(self):
        self.peer('full_protocol')
        self.assertTrue(self.app.dispatch('start_context_diagnostic', {'run_id': self.identifier})['ok'])
        result = self.wait()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error']['code'], 'context_evidence_invalid')
        self.assertFalse(result['context_verified'])

    def test_named_execute_call_without_running_large_generator_cannot_prove_routing(self):
        self.peer('wrong_generator')
        self.assertTrue(self.app.dispatch('start_context_diagnostic', {'run_id': self.identifier})['ok'])
        result = self.wait()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error']['code'], 'context_routing_unverified')
        self.assertFalse(result['context_verified'])


if __name__ == '__main__':
    unittest.main()
