"""Public queue/manual admission with real native artifacts and a controlled peer."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import select
import subprocess
import sys
import time
import unittest

import test_webui_export as export_tests
from app.service import Application

ROOT = Path(__file__).resolve().parents[1]
PROOF = Path(os.environ.get('OCR_DESCENDANT_PROOF', ROOT / '.scratch/ticket-23-proof/descendant-guards'))


class DescendantGuardTests(unittest.TestCase):
    def setUp(self):
        export_tests.AutonomousExportTests.setUp(self)
        self.app.close()
        peer = ROOT / 'tests/descendant_guard_app_server_fixture.py'
        corrections = ROOT / 'tests/corrections_app_server_fixture.py'
        self.runtime = {**self.runtime,
            'files': [*self.runtime['files'], *[{'path': str(p),
                'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in (peer, corrections)]]}
        self.configure_mode('unknown')
        self.app = self.open_app()
        def preserve():
            self.app.close()
            destination = PROOF / (self._testMethodName + '-' + str(time.time_ns()))
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.directory, destination)
            (destination / 'origin.json').write_text(json.dumps({'original': str(self.directory),
                'preserved': str(destination), 'kind': 'controlled peer and real native artifacts; no actual AI'}))
        self.addCleanup(preserve)

    def open_app(self):
        return Application(self.root, codex_runtime=self.runtime, context_runtime=self.context,
            process_command=[sys.executable, '-B', str(ROOT / 'tools/ocr_projects.py')])

    def configure_mode(self, mode):
        wrapper = self.directory / ('descendant-peer-' + mode + '.py')
        wrapper.write_text('import runpy,sys\nsys.argv.insert(1,' + repr(mode) + ')\nrunpy.run_path(' +
            repr(str(ROOT / 'tests/descendant_guard_app_server_fixture.py')) + ',run_name="__main__")\n')
        self.runtime = {**self.runtime, 'command': [sys.executable, '-B', str(wrapper)],
            'files': [*self.runtime['files'], {'path': str(wrapper),
                'sha256': hashlib.sha256(wrapper.read_bytes()).hexdigest()}]}

    def request(self, operation, payload=None):
        response = self.app.dispatch(operation, payload)
        self.assertTrue(response['ok'], response)
        return response['data']

    def enqueue(self, name):
        profile = ROOT / 'profiles/faithful-reading.json'
        return self.request('enqueue_run', {'source_path': str(self.source), 'name': name,
            'profile_path': str(profile), 'profile_sha256': hashlib.sha256(profile.read_bytes()).hexdigest(),
            'environment': os.environ.get('OCR_ENVIRONMENT'), 'request_id': name})

    def wait_queue(self):
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            status = self.request('queue_status')
            if status['state'] != 'running':
                return status
            time.sleep(.04)
        self.fail('Queue did not stop: ' + repr(status))

    def test_unknown_output_descendant_blocks_queue_and_new_admission_despite_foreign_terminal(self):
        self.queue_scenario('unknown')

    def test_accepted_output_with_foreign_turn_and_missing_local_terminal_cannot_replay(self):
        self.app.close()
        self.configure_mode('accepted')
        self.app = self.open_app()
        self.queue_scenario('accepted')

    def test_foreign_started_and_terminal_without_correlated_ack_keep_the_outgoing_unknown(self):
        self.app.close()
        self.configure_mode('foreign_started')
        self.app = self.open_app()
        saved = self.queue_scenario('unknown')
        identity = {'run_id': saved['output']['run_id'],
            'attempt_id': saved['output']['parent_binding']['parent_attempt_id']}
        checked = self.request('reconcile_autonomous', identity)
        self.assertFalse(checked['provider']['safe_to_continue'], checked)
        self.assertTrue(all(row.get('turn_id') != 'foreign-turn' for row in checked['provider']['turns']), checked)
        refused = self.app.dispatch('resume_autonomous', {**identity,
            'reconciliation_id': checked['reconciliation_id']})
        self.assertFalse(refused['ok'], refused)
        self.assertEqual(saved['protocol'].read_bytes(), saved['retained'])

    def queue_scenario(self, delivery):
        first, second = self.enqueue('Original correction output'), self.enqueue('Must stay pending')
        self.request('resume_queue')
        status = self.wait_queue()
        self.assertEqual(status['state'], 'blocked', status)
        reason = status['reason']
        self.assertEqual(reason['delivery_state'], delivery, reason)
        self.assertEqual(reason['scope'], 'global', reason)
        self.assertEqual(reason['stage'], 'output_review', reason)
        self.assertEqual(reason['parent_attempt_id'], status['items'][0]['parent_attempt_id'])
        self.assertIsNone(status['items'][1]['parent_attempt_id'])
        self.assertIn(second['item_id'], status['pending'])
        self.assertTrue(status['items'][0]['waiting_intervals'])
        self.assertIsNone(status['items'][0]['waiting_intervals'][-1]['end'])
        detail = self.request('select_run', {'run_id': first['run_id']})
        work = self.root / detail['artifacts']['workspace']['path']
        correction = self.request('correction_status', {'run_id': first['run_id']})
        output = self.request('output_review_status', {'run_id': first['run_id']})
        self.assertEqual(reason['correction_attempt_id'], correction['attempt_id'])
        self.assertEqual(reason['cycle_id'], correction['cycles'][0]['cycle_id'])
        self.assertEqual(reason['child_attempt_id'], output['attempt_id'])
        self.assertNotEqual(reason['turn_id'], 'foreign-turn')
        self.assertEqual(reason['visual_stage'], 'output_examination')
        if delivery == 'accepted':
            self.assertEqual(reason['turn_id'], 'owned-output-turn')
        protocol = self.root / reason['evidence_path']
        retained = protocol.read_bytes()
        self.assertEqual(hashlib.sha256(retained).hexdigest(), reason['evidence_sha256'])
        for operation in ('start_preparation', 'start_autonomous'):
            refused = self.app.dispatch(operation, {'run_id': second['run_id']})
            self.assertFalse(refused['ok'], refused)
        self.app.close()
        self.app = self.open_app()
        refused = self.app.dispatch('start_preparation', {'run_id': second['run_id']})
        self.assertFalse(refused['ok'], refused)
        self.assertEqual(refused['error']['code'], 'reconciliation_required')
        self.assertEqual(protocol.read_bytes(), retained)
        self.assertEqual(len(list((work / 'application/correction-attempts').glob('*/attempt.json'))), 1)
        self.assertEqual(correction['cycles_used'], 1)
        self.assertIsNone(correction['stop_reason'])
        self.assertNotEqual(correction['cycles'][0]['state'], 'settled')
        self.assertNotIn('outcome', correction['cycles'][0])
        metrics = self.request('run_metrics', {'run_id': first['run_id']})
        output_steps = [step for step in metrics['steps'] if step.get('attempt_id') == output['attempt_id']]
        self.assertTrue(output_steps, metrics)
        self.assertTrue(all(step['tokens']['values'] is None for step in output_steps), output_steps)
        if delivery == 'accepted':
            identity = {'run_id': first['run_id'], 'attempt_id': reason['parent_attempt_id']}
            checked = self.request('reconcile_autonomous', identity)
            self.assertFalse(checked['provider']['safe_to_continue'], checked)
            self.assertTrue(any(row['attempt_id'] == output['attempt_id'] and row['state'] == 'completed'
                for row in checked['provider']['turns']), checked)
            self.assertEqual(checked['provider']['continuation_error']['code'], 'original_result_unavailable', checked)
            refused = self.app.dispatch('resume_autonomous', {**identity,
                'reconciliation_id': checked['reconciliation_id']})
            self.assertFalse(refused['ok'], refused)
            self.assertEqual(protocol.read_bytes(), retained)
        return {'work': work, 'output': output, 'second': second, 'protocol': protocol, 'retained': retained}

    def test_foreign_and_multiple_output_claimants_refuse_manual_admission_without_a_new_turn(self):
        case = self.queue_scenario('unknown')
        path = case['work'] / 'application/output-review-attempts' / case['output']['attempt_id'] / 'attempt.json'
        original = path.read_bytes()
        (self.directory / 'original-output-before-injected-conflicts.json').write_bytes(original)
        foreign = json.loads(original)
        foreign['parent_binding']['correction_attempt_id'] = 'f' * 32
        path.write_text(json.dumps(foreign))
        refused = self.app.dispatch('start_preparation', {'run_id': case['second']['run_id']})
        self.assertFalse(refused['ok'], refused)
        self.assertEqual(refused['error']['code'], 'attempt_conflict', refused)
        path.write_bytes(original)
        duplicate = json.loads(original)
        duplicate['attempt_id'] = 'f' * 32
        duplicate_path = path.parent.parent / duplicate['attempt_id'] / 'attempt.json'
        duplicate_path.parent.mkdir()
        duplicate_path.write_text(json.dumps(duplicate))
        (self.directory / 'injected-conflicts.json').write_text(json.dumps({
            'kind': 'adversarial application-manifest claims only; no native/provider artifact fabricated',
            'foreign_binding': foreign['parent_binding'], 'duplicate_manifest': str(duplicate_path)}))
        refused = self.app.dispatch('start_preparation', {'run_id': case['second']['run_id']})
        self.assertFalse(refused['ok'], refused)
        self.assertEqual(refused['error']['code'], 'attempt_conflict', refused)
        self.assertEqual(case['protocol'].read_bytes(), case['retained'])

    def test_typed_output_rejections_keep_original_quota_authentication_and_network_evidence(self):
        variants = {'quota': 'usageLimitExceeded', 'authentication': 'unauthorized', 'network': 'httpConnectionFailed'}
        for category, variant in variants.items():
            with self.subTest(category=category):
                self.app.close()
                self.root = self.directory / category / 'registry'
                self.root.parent.mkdir()
                self.configure_mode(category)
                self.app = self.open_app()
                first, second = self.enqueue('Typed original ' + category), self.enqueue('Pending after ' + category)
                self.request('resume_queue')
                status = self.wait_queue()
                self.assertEqual(status['state'], 'blocked', status)
                reason = status['reason']
                self.assertEqual(reason['stage'], 'output_review', reason)
                self.assertEqual(reason['delivery_state'], 'rejected', reason)
                self.assertEqual(reason['scope'], 'global', reason)
                self.assertEqual(reason['category'], category, reason)
                self.assertEqual(reason['original_error']['data']['codexErrorInfo'], variant)
                self.assertEqual(reason['visual_stage'], 'output_examination')
                self.assertIsNone(reason['turn_id'])
                output = self.request('output_review_status', {'run_id': first['run_id']})
                self.assertEqual(reason['child_attempt_id'], output['attempt_id'])
                correction = self.request('correction_status', {'run_id': first['run_id']})
                self.assertEqual(reason['correction_attempt_id'], correction['attempt_id'])
                self.assertEqual(reason['cycle_id'], correction['cycles'][0]['cycle_id'])
                self.assertEqual(correction['cycles_used'], 1)
                protocol = self.root / reason['evidence_path']
                retained = protocol.read_bytes()
                self.assertEqual(hashlib.sha256(retained).hexdigest(), reason['evidence_sha256'])
                self.assertIsNone(status['items'][1]['parent_attempt_id'])
                self.assertIn(second['item_id'], status['pending'])
                self.app.close()
                self.app = self.open_app()
                self.assertEqual(self.request('queue_status')['reason'], reason)
                self.assertEqual(protocol.read_bytes(), retained)

    def test_manual_output_rejection_holds_global_admission_with_truthful_rejected_delivery(self):
        self.app.close()
        self.configure_mode('quota')
        self.app = self.open_app()
        profile = ROOT / 'profiles/faithful-reading.json'
        started = self.request('start_autonomous', {'source_path': str(self.source), 'name': 'Manual output rejection',
            'profile_path': str(profile), 'profile_sha256': hashlib.sha256(profile.read_bytes()).hexdigest(),
            'defer_corrections': True, 'environment': os.environ.get('OCR_ENVIRONMENT')})
        identity = {'run_id': started['run_id']}
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            parent = self.request('autonomous_status', identity)
            if parent['state'] not in ('starting', 'running'):
                break
            time.sleep(.04)
        self.assertEqual(parent['state'], 'completed', parent)
        other = self.enqueue('Do not bypass manual global failure')
        detail = self.request('select_run', identity)
        work = self.root / detail['artifacts']['workspace']['path']
        manifest = json.loads((work / 'output-manifest.json').read_text())
        correction = self.request('start_corrections', {**identity,
            'expected_iteration_id': manifest['iteration_id'],
            'expected_validation_sha256': hashlib.sha256((work / 'checks/run-validation.json').read_bytes()).hexdigest(),
            'environment': os.environ.get('OCR_ENVIRONMENT')})
        deadline = time.monotonic() + 100
        while time.monotonic() < deadline:
            status = self.request('queue_status')
            manual = status['manual_execution']
            if manual and manual['state'] != 'running':
                break
            time.sleep(.04)
        self.assertEqual(manual['state'], 'reconciliation_required', manual)
        self.assertEqual(manual['child_attempt_id'], correction['attempt_id'])
        self.assertEqual(manual['delivery_state'], 'rejected')
        self.assertEqual(manual['failure']['scope'], 'global')
        self.assertEqual(manual['failure']['category'], 'quota')
        self.assertEqual(manual['failure']['stage'], 'output_review')
        self.assertIsNone(manual['failure']['parent_attempt_id'])
        self.assertEqual(manual['descendants'][-1]['manual_id'], manual['manual_id'])
        output = self.request('output_review_status', identity)
        self.assertEqual(manual['failure']['child_attempt_id'], output['attempt_id'])
        protocol = self.root / manual['failure']['evidence_path']
        retained = protocol.read_bytes()
        self.app.close()
        self.app = self.open_app()
        refused = self.app.dispatch('start_preparation', {'run_id': other['run_id']})
        self.assertFalse(refused['ok'], refused)
        self.assertEqual(refused['error']['code'], 'reconciliation_required')
        self.request('resume_queue')
        self.assertEqual(self.wait_queue()['state'], 'blocked')
        self.assertEqual(protocol.read_bytes(), retained)

    def test_output_manifest_before_parent_link_still_blocks_queue_with_exact_original_evidence(self):
        self.owner_crash_scenario('link')

    def test_completed_terminal_cannot_regress_after_duplicate_terminal_ack_and_late_started(self):
        self.app.close()
        self.configure_mode('completed_late_started')
        self.app = self.open_app()
        first, second = self.enqueue('Terminal must stay terminal'), self.enqueue('Pending after local validation failure')
        self.request('resume_queue')
        status = self.wait_queue()
        self.assertEqual(status['state'], 'blocked', status)
        reason = status['reason']
        self.assertEqual(reason['delivery_state'], 'completed', reason)
        self.assertEqual(reason['scope'], 'global')
        self.assertEqual(reason['category'], 'reconciliation')
        self.assertEqual(reason['stage'], 'output_review')
        output = self.request('output_review_status', {'run_id': first['run_id']})
        self.assertEqual(reason['child_attempt_id'], output['attempt_id'])
        self.assertFalse(output['output_review_complete'])
        protocol = self.root / reason['evidence_path']
        retained = protocol.read_bytes()
        events = [json.loads(row)['message'].get('method') for row in retained.splitlines()]
        self.assertEqual(events.count('turn/completed'), 2)
        self.assertEqual(events[-1], 'turn/started')
        self.assertIsNone(status['items'][1]['parent_attempt_id'])
        self.assertIn(second['item_id'], status['pending'])
        self.app.close()
        self.app = self.open_app()
        self.assertEqual(self.request('queue_status')['reason'], reason)
        self.assertEqual(protocol.read_bytes(), retained)

    def owner_crash_scenario(self, fault):
        self.app.close()
        if fault == 'terminal':
            self.configure_mode('completed_late_started')
        runtime, context = self.directory / 'runtime.json', self.directory / 'context.json'
        runtime.write_text(json.dumps(self.runtime)); context.write_text(json.dumps(self.context))
        marker = self.directory / 'before-output-link.json'
        stderr = (self.directory / 'owner-stderr.log').open('wb')
        process = subprocess.Popen([sys.executable, '-B', str(ROOT / 'tests/descendant_guard_app_server_fixture.py'),
            '--owner', str(self.root), str(runtime), str(context), str(marker), fault],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, text=True)
        (self.directory / 'owner.json').write_text(json.dumps({'pid': process.pid,
            'start_ticks': Path('/proc', str(process.pid), 'stat').read_text().rsplit(')', 1)[1].split()[19]}))
        def finish():
            if process.poll() is None:
                process.terminate(); process.wait(timeout=10)
            process.stdin.close(); process.stdout.close(); stderr.close()
        self.addCleanup(finish)
        def request(operation, payload=None):
            process.stdin.write(json.dumps({'operation': operation, 'payload': payload}) + '\n')
            process.stdin.flush()
            self.assertTrue(select.select([process.stdout], [], [], 15)[0], 'Owned application response timed out')
            response = json.loads(process.stdout.readline())
            self.assertTrue(response['ok'], response)
            return response['data']
        profile = ROOT / 'profiles/faithful-reading.json'
        first = request('enqueue_run', {'source_path': str(self.source), 'name': 'Unlinked output child',
            'profile_path': str(profile), 'profile_sha256': hashlib.sha256(profile.read_bytes()).hexdigest(),
            'environment': os.environ.get('OCR_ENVIRONMENT'), 'request_id': 'unlinked-first'})
        second = request('enqueue_run', {'source_path': str(self.source), 'name': 'Pending during owner crash',
            'profile_path': str(profile), 'profile_sha256': hashlib.sha256(profile.read_bytes()).hexdigest(),
            'environment': os.environ.get('OCR_ENVIRONMENT'), 'request_id': 'unlinked-second'})
        request('resume_queue')
        self.assertEqual(process.wait(timeout=150), 91, (self.directory / 'owner-stderr.log').read_text()[-2000:])
        crashed = json.loads(marker.read_text())
        self.app = self.open_app()
        status = self.request('queue_status')
        reason = status['items'][0]['reason']
        self.assertIn(status['state'], ('blocked', 'paused'))
        self.assertEqual(reason['delivery_state'], 'completed' if fault == 'terminal' else 'not_submitted', reason)
        if fault == 'link':
            self.assertTrue(reason['pending_descendant'], reason)
            self.assertIn(reason['child_state'], ('starting', 'running'))
        self.assertEqual(reason['stage'], 'output_review', reason)
        self.assertEqual(reason['child_attempt_id'], crashed['output_attempt_id'])
        self.assertEqual(reason['correction_attempt_id'], crashed['correction_attempt_id'])
        self.assertEqual(reason['cycle_id'], crashed['cycle_id'])
        detail = self.request('select_run', {'run_id': first['run_id']})
        work = self.root / detail['artifacts']['workspace']['path']
        correction_path = work / 'application/correction-attempts' / crashed['correction_attempt_id'] / 'attempt.json'
        self.assertEqual(hashlib.sha256(correction_path.read_bytes()).hexdigest(), crashed['original_correction_sha256'])
        self.assertEqual(bool(json.loads(correction_path.read_text()).get('children')), fault == 'terminal')
        evidence = self.root / reason['evidence_path']
        retained = evidence.read_bytes()
        self.assertEqual(hashlib.sha256(retained).hexdigest(), reason['evidence_sha256'])
        if fault == 'link':
            self.assertEqual(json.loads(retained)['attempt_id'], crashed['output_attempt_id'])
        else:
            events = [json.loads(row)['message'].get('method') for row in retained.splitlines()]
            self.assertEqual(events.count('turn/completed'), 2)
            self.assertEqual(events[-1], 'turn/started')
        self.request('queue_status')
        self.assertEqual(evidence.read_bytes(), retained)
        self.assertIsNone(status['items'][1]['parent_attempt_id'])


if __name__ == '__main__':
    unittest.main()
