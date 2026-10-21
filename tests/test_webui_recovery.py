"""Public lifecycle, native subprocesses and a controlled app-server peer."""
import json
import os
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from app.service import Application
import test_webui_export as export_tests


class RecoveryTests(unittest.TestCase):
    setUp = export_tests.AutonomousExportTests.setUp

    def start(self):
        profile = self.app.dispatch('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})['data']
        result = self.app.dispatch('start_autonomous', {'source_path': str(self.source), 'name': 'Recover me',
            'profile_path': profile['path'], 'profile_sha256': profile['sha256'],
            'environment': getattr(self, 'environment', os.environ.get('OCR_ENVIRONMENT'))})
        self.assertTrue(result['ok'], result)
        return result['data']

    def wait(self, run_id, terminal=('paused', 'completed', 'failed', 'interrupted')):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            result = self.app.dispatch('autonomous_status', {'run_id': run_id})
            self.assertTrue(result['ok'], result)
            if result['data']['state'] in terminal:
                return result['data']
            time.sleep(.03)
        self.fail('Lifecycle did not settle: ' + repr(result))

    def interrupt_peer(self, mode):
        self.app.close()
        self.peer_state = self.directory / 'provider-state.json'
        self.runtime = {**self.runtime, 'command': [sys.executable, '-B',
            str(ROOT / 'tests/codex_app_server_fixture.py'), mode, str(self.peer_state)]}
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)

    def test_pause_restart_and_resume_preserve_the_same_run_and_verified_work(self):
        first = self.start()
        identity = {'run_id': first['run_id'], 'attempt_id': first['attempt_id']}
        paused = self.app.dispatch('pause_autonomous', identity)
        self.assertTrue(paused['ok'], paused)
        saved = self.wait(first['run_id'])
        self.assertEqual(saved['state'], 'paused', saved)
        self.app.close()
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        status = self.app.dispatch('autonomous_status', identity)['data']
        self.assertEqual(status['state'], 'paused')
        checked = self.app.dispatch('reconcile_autonomous', identity)
        self.assertTrue(checked['ok'], checked)
        self.assertTrue(checked['data']['checkpoint']['valid'], checked)
        resumed = self.app.dispatch('resume_autonomous', {**identity,
            'reconciliation_id': checked['data']['reconciliation_id']})
        self.assertTrue(resumed['ok'], resumed)
        complete = self.wait(first['run_id'])
        self.assertEqual(complete['state'], 'completed', complete)
        self.assertEqual(complete['run_id'], first['run_id'])
        self.assertEqual(complete['attempt_id'], first['attempt_id'])

    def test_pause_stops_native_unit_admission_and_interrupt_preserves_completed_units(self):
        import fitz
        with fitz.open(self.source) as original:
            with fitz.open() as many:
                for _ in range(10):
                    many.insert_pdf(original)
                path = self.directory / 'many.pdf'
                many.save(path)
        self.source = path
        first = self.start()
        identity = {'run_id': first['run_id'], 'attempt_id': first['attempt_id']}
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            preparation = self.app.dispatch('preparation_status', identity)['data']
            if any(step.startswith('ocr:') for step in preparation.get('active_steps', [])):
                break
            time.sleep(.01)
        self.assertTrue(self.app.dispatch('pause_autonomous', identity)['ok'])
        paused = self.wait(first['run_id'])
        self.assertEqual(paused['state'], 'paused', paused)
        preparation = self.app.dispatch('preparation_status', identity)['data']
        self.assertEqual(preparation['state'], 'paused', preparation)
        self.assertLess(preparation['counts']['ocr_completed'], 40)
        self.assertFalse(preparation['checkpoint_valid'])
        selected = self.app.dispatch('select_run', identity)['data']
        work = self.root / selected['artifacts']['workspace']['path']
        self.assertEqual(json.loads((work / 'preparation-checkpoint.json').read_text())['status'], 'paused')
        events = preparation['events']
        requested = next(i for i, event in enumerate(events) if event['type'] == 'pause_requested')
        later = events[requested + 1:]
        self.assertFalse(any(event['type'] == 'unit_started' for event in later))
        self.assertLessEqual(sum(event['type'] == 'unit_completed' for event in later), 2)
        import hashlib
        retained = {str(p.relative_to(work)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                    for p in work.rglob('*') if p.is_file() and p.suffix in ('.png', '.hocr')}
        checked = self.app.dispatch('reconcile_autonomous', identity)
        self.assertTrue(checked['ok'], checked)
        self.assertTrue(checked['data']['checkpoint']['valid'], checked)
        resumed = self.app.dispatch('resume_autonomous', {**identity,
            'reconciliation_id': checked['data']['reconciliation_id']})
        self.assertTrue(resumed['ok'], resumed)
        old_attempt = preparation['attempt_id']
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            preparation = self.app.dispatch('preparation_status', identity)['data']
            if preparation['attempt_id'] != old_attempt and (
                    any(event['type'] == 'unit_cached' for event in preparation['events']) or
                    preparation['state'] in ('failed', 'interrupted')):
                break
            time.sleep(.01)
        self.assertNotEqual(preparation['attempt_id'], old_attempt)
        self.assertTrue(any(event['type'] == 'unit_cached' for event in preparation['events']), preparation)
        self.assertTrue(self.app.dispatch('pause_autonomous', identity)['ok'])
        self.assertEqual(self.wait(first['run_id'])['state'], 'paused')
        for relative, original in retained.items():
            p = work / relative
            self.assertEqual((hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns), original, relative)

    def test_interrupt_real_native_work_then_reject_changed_source_before_resume(self):
        first = self.start()
        identity = {'run_id': first['run_id'], 'attempt_id': first['attempt_id']}
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            local = self.app.dispatch('preparation_status', identity)['data']
            if local.get('process_group') and local.get('active_steps'):
                break
            time.sleep(.01)
        self.assertTrue(local.get('process_group'), local)
        self.assertTrue(self.app.dispatch('interrupt_autonomous', identity)['ok'])
        final = self.wait(first['run_id'])
        self.assertEqual(final['state'], 'interrupted', final)
        local = self.app.dispatch('preparation_status', identity)['data']
        self.assertEqual(local['state'], 'interrupted')
        with self.assertRaises(ProcessLookupError):
            os.killpg(local['process_group'], 0)
        self.app.close()
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        detail = self.app.dispatch('select_run', identity)['data']
        stored = self.root / detail['artifacts']['source']['path']
        original = stored.read_bytes()
        stored.write_bytes(original + b'changed')
        rejected = self.app.dispatch('reconcile_autonomous', identity)
        self.assertFalse(rejected['ok'])
        self.assertEqual(rejected['error']['code'], 'source_corrupt')

    def test_controlled_ai_interrupt_reconciles_exact_original_turn_and_retains_usage(self):
        self.interrupt_peer('hold')
        first = self.start()
        identity = {'run_id': first['run_id'], 'attempt_id': first['attempt_id']}
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            original = self.app.dispatch('model_diagnostic_status', identity)['data']
            if self.peer_state.exists() and original.get('turn_id'):
                break
            time.sleep(.02)
        self.assertTrue(original.get('turn_id'), original)
        other = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        self.addCleanup(other.close)
        run_ids_before = [row['run_id'] for row in other.dispatch('projects')['data']['editions'][0]['runs']]
        profile = self.app.dispatch('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})['data']
        blocked = other.dispatch('start_autonomous', {'source_path': str(self.source), 'name': 'Competing start',
            'profile_path': profile['path'], 'profile_sha256': profile['sha256'], 'environment': os.environ.get('OCR_ENVIRONMENT')})
        self.assertFalse(blocked['ok'])
        self.assertEqual(blocked['error']['code'], 'operation_active')
        self.assertEqual([row['run_id'] for row in other.dispatch('projects')['data']['editions'][0]['runs']], run_ids_before)
        self.assertTrue(self.app.dispatch('interrupt_autonomous', identity)['ok'])
        stopped = self.wait(first['run_id'])
        self.assertEqual(stopped['state'], 'interrupted')
        original = self.app.dispatch('model_diagnostic_status', identity)['data']
        self.assertEqual(original['terminal_turn']['status'], 'interrupted')
        self.assertEqual(original['usage_events'][0]['tokenUsage']['total']['inputTokens'], 31)
        protocol = self.root / original['artifacts']['protocol']
        before = protocol.read_bytes()
        self.assertIn(b'turn/interrupt', before)
        self.app.close()
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        proof = self.app.dispatch('reconcile_autonomous', identity)
        self.assertTrue(proof['ok'], proof)
        self.assertEqual(proof['data']['provider']['turns'][0]['state'], 'interrupted')
        self.assertEqual(proof['data']['provider']['turns'][0]['turn_id'], 'fixture-turn-13')
        self.assertEqual(protocol.read_bytes(), before)
        # Provider recovery and the OCR checkpoint have independent truth.
        detail = self.app.dispatch('select_run', identity)['data']
        work = self.root / detail['artifacts']['workspace']['path']
        (work / 'ocr/page-1-psm3.hocr').write_text('tampered completed local artifact')
        independent = self.app.dispatch('reconcile_autonomous', identity)
        self.assertTrue(independent['ok'], independent)
        self.assertFalse(independent['data']['checkpoint']['valid'])
        self.assertEqual(independent['data']['provider']['turns'][0]['state'], 'interrupted')
        denied = self.app.dispatch('resume_autonomous', {**identity,
            'reconciliation_id': independent['data']['reconciliation_id']})
        self.assertFalse(denied['ok'])
        self.assertEqual(denied['error']['code'], 'checkpoint_invalid')

    def test_completed_provider_without_local_result_cannot_submit_a_replacement_turn(self):
        self.interrupt_peer('completed_lost_terminal')
        first = self.start()
        identity = {'run_id': first['run_id'], 'attempt_id': first['attempt_id']}
        self.assertEqual(self.wait(first['run_id'])['state'], 'failed')
        original = self.app.dispatch('model_diagnostic_status', identity)['data']
        self.assertEqual(original['turn_id'], 'fixture-turn-13')
        self.assertIsNone(original.get('terminal_turn'))
        protocol = self.root / original['artifacts']['protocol']
        before = protocol.read_bytes()
        self.assertNotIn(b'turn/completed', before)
        checked = self.app.dispatch('reconcile_autonomous', identity)
        self.assertTrue(checked['ok'], checked)
        self.assertTrue(checked['data']['checkpoint']['valid'], checked)
        self.assertEqual(checked['data']['provider']['turns'][0]['state'], 'completed')
        self.assertFalse(checked['data']['provider']['safe_to_continue'])
        resumed = self.app.dispatch('resume_autonomous', {**identity,
            'reconciliation_id': checked['data']['reconciliation_id']})
        if resumed['ok']:
            self.wait(first['run_id'])
        self.assertEqual(json.loads(self.peer_state.read_text())['start_count'], 1)
        self.assertFalse(resumed['ok'], resumed)
        self.assertEqual(resumed['error']['code'], 'original_result_unavailable')
        self.assertEqual(protocol.read_bytes(), before)

    def test_lost_submission_ack_remains_unknown_and_cannot_be_replayed(self):
        self.interrupt_peer('lost_ack')
        first = self.start()
        identity = {'run_id': first['run_id'], 'attempt_id': first['attempt_id']}
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline and not self.peer_state.exists():
            time.sleep(.03)
        self.assertTrue(self.peer_state.exists())
        self.assertTrue(self.app.dispatch('interrupt_autonomous', identity)['ok'])
        self.assertEqual(self.wait(first['run_id'])['state'], 'interrupted')
        checked = self.app.dispatch('reconcile_autonomous', identity)
        self.assertTrue(checked['ok'], checked)
        self.assertEqual(checked['data']['provider']['state'], 'unknown')
        rejected = self.app.dispatch('resume_autonomous', {**identity,
            'reconciliation_id': checked['data']['reconciliation_id']})
        self.assertFalse(rejected['ok'])
        self.assertEqual(rejected['error']['code'], 'reconciliation_required')
        manual = self.app.dispatch('start_model_diagnostic', identity)
        self.assertFalse(manual['ok'])
        self.assertEqual(manual['error']['code'], 'reconciliation_required')

    def test_pause_between_reading_turns_reuses_completed_source_in_new_attempt(self):
        import hashlib
        self.app.close()
        gate = self.directory / 'release-source'
        wrapper = self.directory / 'gated-peer.py'
        wrapper.write_text('import os,runpy\nos.environ["RECOVERY_SOURCE_GATE"]=' + repr(str(gate)) +
            '\nrunpy.run_path(' + repr(str(ROOT / 'tests/autonomous_app_server_fixture.py')) + ',run_name="__main__")\n')
        self.runtime = {**self.runtime, 'command': [sys.executable, '-B', str(wrapper)],
            'files': [*self.runtime['files'], {'path': str(wrapper), 'sha256': hashlib.sha256(wrapper.read_bytes()).hexdigest()}]}
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        first = self.start()
        identity = {'run_id': first['run_id'], 'attempt_id': first['attempt_id']}
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline and not Path(str(gate) + '.ready').exists():
            time.sleep(.03)
        self.assertTrue(Path(str(gate) + '.ready').exists())
        self.assertTrue(self.app.dispatch('pause_autonomous', identity)['ok'])
        gate.write_text('finish only the admitted source turn')
        self.assertEqual(self.wait(first['run_id'])['state'], 'paused')
        original = self.app.dispatch('reading_status', identity)['data']
        self.assertEqual([row['stage'] for row in original['turns']], ['source'])
        original_protocol = (self.root / original['artifacts']['protocol']).read_bytes()
        checked = self.app.dispatch('reconcile_autonomous', identity)
        self.assertTrue(checked['ok'], checked)
        self.assertTrue(checked['data']['checkpoint']['valid'], checked)
        self.assertTrue(self.app.dispatch('resume_autonomous', {**identity,
            'reconciliation_id': checked['data']['reconciliation_id']})['ok'])
        finished = self.wait(first['run_id'])
        self.assertEqual(finished['state'], 'completed', finished.get('error'))
        current = self.app.dispatch('reading_status', identity)['data']
        self.assertNotEqual(current['attempt_id'], original['attempt_id'])
        protocol = (self.root / current['artifacts']['protocol']).read_text()
        self.assertIn('thread/resume', protocol)
        self.assertNotIn('ORIGINAL_SOURCE_PACKET', protocol)
        self.assertEqual((self.root / original['artifacts']['protocol']).read_bytes(), original_protocol)

    def test_resume_rechecks_environment_and_immutable_profile_after_reconciliation(self):
        original = Path(os.environ['OCR_ENVIRONMENT'])
        environment = json.loads(original.read_text())
        environment['root'] = str((original.parent / environment.get('root', '.')).resolve())
        selected = self.directory / 'selected environment.json'
        selected.write_text(json.dumps(environment))
        self.environment = str(selected)
        first = self.start()
        identity = {'run_id': first['run_id'], 'attempt_id': first['attempt_id']}
        self.assertTrue(self.app.dispatch('pause_autonomous', identity)['ok'])
        self.assertEqual(self.wait(first['run_id'])['state'], 'paused')
        checked = self.app.dispatch('reconcile_autonomous', identity)
        self.assertTrue(checked['ok'], checked)
        self.assertTrue(checked['data']['checkpoint']['valid'], checked)
        before = selected.read_bytes()
        environment['build_id'] += '-changed'
        selected.write_text(json.dumps(environment))
        denied = self.app.dispatch('resume_autonomous', {**identity,
            'reconciliation_id': checked['data']['reconciliation_id']})
        self.assertFalse(denied['ok'])
        self.assertEqual(denied['error']['code'], 'checkpoint_identity_changed')
        selected.write_bytes(before)
        detail = self.app.dispatch('select_run', identity)['data']
        work = self.root / detail['artifacts']['workspace']['path']
        profile = json.loads((work / 'application/profile.json').read_text())
        profile['parameters']['dpi'] = 150
        (work / 'application/profile.json').write_text(json.dumps(profile))
        rejected = self.app.dispatch('reconcile_autonomous', identity)
        self.assertFalse(rejected['ok'])


if __name__ == '__main__':
    unittest.main()
