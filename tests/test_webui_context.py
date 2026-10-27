"""Context readiness via the approved public application/process boundary."""
import json
import hashlib
import os
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

    def peer(self, mode, *, context_changes=None):
        self.app.close()
        fixture = ROOT / 'tests/context_app_server_fixture.py'
        codex = {'kind': 'controlled_process_fixture', 'version': 'fixture14',
                 'command': [sys.executable, str(fixture), mode],
                 'files': [{'path': str(fixture), 'sha256': hashlib.sha256(fixture.read_bytes()).hexdigest()}]}
        context = {'kind': 'controlled_process_fixture', 'package': str(self.directory), 'node': sys.executable,
                   'files': [], 'interpreters': [], 'probe_command': [sys.executable, '-c',
                       'print(\'{"node":"fixture","sqlite_fts5":true}\')']}
        context.update(context_changes or {})
        self.app = Application(self.registry, codex_runtime=codex, context_runtime=context)

    def bundled_peer(self, *, declare_helper=True):
        helper = self.directory / 'selected-program/runtime/sandbox-bin/bwrap'
        helper.parent.mkdir(parents=True)
        helper.write_text('#!/bin/sh\n# Explicit controlled helper, never native acceptance evidence.\nexit 0\n')
        helper.chmod(0o755)
        pin = {'path': str(helper), 'sha256': hashlib.sha256(helper.read_bytes()).hexdigest()}
        settings = {'bundled': True, 'launcher_commands': {'node': [sys.executable],
            'python3': [sys.executable], 'bash': ['/usr/bin/bash'], 'sh': ['/usr/bin/sh']}}
        if declare_helper:
            settings.update(native_helpers=[{'name': 'bwrap', **pin}], files=[pin])
        self.peer('repair_redirect', context_changes=settings)
        return helper

    def test_installed_runtime_without_declared_sandbox_helper_stops_before_provider(self):
        self.bundled_peer(declare_helper=False)
        self.assertTrue(self.app.dispatch('start_context_diagnostic', {'run_id': self.identifier})['ok'])
        result = self.wait()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error']['code'], 'context_runtime_invalid')
        self.assertIsNone(result['pid'])
        self.assertIsNone(result['turn_id'])
        self.assertFalse(result['context_verified'])

    def test_installed_sandbox_helper_is_on_protected_path_and_not_copied_to_workspace(self):
        helper = self.bundled_peer()
        original = helper.read_bytes()
        self.assertTrue(self.app.dispatch('start_context_diagnostic', {'run_id': self.identifier})['ok'])
        result = self.wait()
        self.assertEqual(result['state'], 'completed', result.get('error'))
        self.assertTrue(result['context_verified'])
        paths = result['effective_context_config']['context_environment']['PATH'].split(os.pathsep)
        self.assertEqual(paths[-1], str(helper.parent))
        workspace = Path(result['context_paths']['workspace'])
        self.assertFalse(helper.is_relative_to(workspace))
        self.assertFalse((Path(paths[0]) / 'bwrap').exists())
        self.assertNotIn('/usr/bin', paths)
        self.assertNotIn('/bin', paths)
        self.assertEqual(helper.read_bytes(), original)

    def test_installed_sandbox_helper_without_execute_permission_stops_before_provider(self):
        helper = self.bundled_peer()
        helper.chmod(0o644)
        self.assertTrue(self.app.dispatch('start_context_diagnostic', {'run_id': self.identifier})['ok'])
        result = self.wait()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error']['code'], 'context_runtime_invalid')
        self.assertIsNone(result['pid'])
        self.assertIsNone(result['turn_id'])

    def test_linked_installed_sandbox_helper_stops_before_provider(self):
        helper = self.bundled_peer()
        original = helper.with_name('original-bwrap')
        helper.rename(original)
        helper.symlink_to(original)
        self.assertTrue(self.app.dispatch('start_context_diagnostic', {'run_id': self.identifier})['ok'])
        result = self.wait()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error']['code'], 'context_runtime_invalid')
        self.assertIsNone(result['pid'])
        self.assertIsNone(result['turn_id'])

    def test_untrusted_actual_hook_metadata_stops_before_any_model_turn(self):
        self.peer('untrusted')
        self.assertTrue(self.app.dispatch('start_context_diagnostic', {'run_id': self.identifier})['ok'])
        result = self.wait()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error']['code'], 'context_hook_untrusted')
        self.assertFalse(result['autonomous_ocr_ready'])
        self.assertIsNone(result['turn_id'])

    def test_completed_lookup_gets_one_targeted_native_routing_correction(self):
        self.peer('repair_redirect')
        started = self.app.dispatch('start_context_diagnostic', {'run_id': self.identifier})
        self.assertTrue(started['ok'], started)
        result = self.wait()
        self.assertEqual(result['state'], 'completed', result.get('error'))
        self.assertTrue(result['context_verified'])
        self.assertFalse(result['autonomous_ocr_ready'])
        self.assertEqual([row['stage'] for row in result['turns']], ['routing', 'routing_correction', 'recovery'])
        self.assertEqual(len({row['thread_id'] for row in result['turns']}), 1)
        self.assertEqual(len({row['turn_id'] for row in result['turns']}), 3)
        requests = json.loads((self.registry / result['artifacts']['request']).read_text())['requests']
        correction = next(row for row in requests if row['stage'] == 'routing_correction')
        self.assertNotIn(result['oracle'], correction['params']['input'][0]['text'])
        corrected = [row['item'] for row in result['completed_items']
                     if row.get('turnId') == result['turns'][1]['turn_id']]
        self.assertTrue(any(row.get('type') == 'commandExecution' for row in corrected))
        self.assertFalse(any(row.get('type') == 'mcpToolCall' for row in corrected))

    def test_native_routing_still_missing_after_one_correction_stops_without_another_turn(self):
        self.peer('repair_redirect_missing')
        self.assertTrue(self.app.dispatch('start_context_diagnostic', {'run_id': self.identifier})['ok'])
        result = self.wait()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error']['code'], 'context_routing_unverified')
        self.assertFalse(result['context_verified'])
        self.assertEqual([row['stage'] for row in result['turns']], ['routing', 'routing_correction'])
        requests = self.registry / result['artifacts']['request']
        original = requests.read_bytes()
        self.assertEqual(len(json.loads(original)['requests']), 2)
        self.app.close()
        self.app = Application(self.registry)
        status = self.app.dispatch('context_status', {'run_id': self.identifier})
        self.assertTrue(status['ok'], status)
        self.assertEqual(status['data']['state'], 'failed')
        self.assertFalse(status['data']['context_verified'])
        self.assertEqual(requests.read_bytes(), original)

    def test_unfinished_routing_turn_never_starts_a_corrective_request(self):
        self.peer('repair_redirect_unknown')
        self.assertTrue(self.app.dispatch('start_context_diagnostic', {'run_id': self.identifier})['ok'])
        result = self.wait()
        self.assertEqual(result['state'], 'failed')
        self.assertFalse(result['context_verified'])
        self.assertEqual([row['stage'] for row in result['turns']], ['routing'])
        self.assertEqual(result['turns'][0]['state'], 'running')
        requests = json.loads((self.registry / result['artifacts']['request']).read_text())['requests']
        self.assertEqual(len(requests), 1)

    def test_started_native_command_without_completion_never_starts_a_corrective_request(self):
        self.peer('repair_redirect_started')
        self.assertTrue(self.app.dispatch('start_context_diagnostic', {'run_id': self.identifier})['ok'])
        result = self.wait()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error']['code'], 'context_routing_unverified')
        self.assertFalse(result['context_verified'])
        self.assertEqual([row['stage'] for row in result['turns']], ['routing'])
        self.assertEqual(result['turns'][0]['state'], 'completed')
        requests = json.loads((self.registry / result['artifacts']['request']).read_text())['requests']
        self.assertEqual(len(requests), 1)

    def test_incorrect_lookup_answer_never_starts_a_native_routing_correction(self):
        self.peer('repair_redirect_bad_answer')
        self.assertTrue(self.app.dispatch('start_context_diagnostic', {'run_id': self.identifier})['ok'])
        result = self.wait()
        self.assertEqual(result['state'], 'failed')
        self.assertFalse(result['context_verified'])
        self.assertEqual([row['stage'] for row in result['turns']], ['routing'])
        requests = json.loads((self.registry / result['artifacts']['request']).read_text())['requests']
        self.assertEqual(len(requests), 1)

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
