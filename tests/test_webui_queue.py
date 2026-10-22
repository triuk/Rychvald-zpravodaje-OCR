"""Queue behavior at the GUI's public request boundary; controlled peers only."""
import json
import hashlib
import os
import signal
from pathlib import Path
import sys
import subprocess
import shutil
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from app.service import Application
import test_webui_export as export_tests


class QueueTests(unittest.TestCase):
    def setUp(self):
        export_tests.AutonomousExportTests.setUp(self)
        proof = os.environ.get('QUEUE_PROOF_ROOT')
        if proof:
            def preserve():
                self.app.close()
                destination = Path(proof) / self.id().split('.')[-1]
                shutil.copytree(self.directory, destination, dirs_exist_ok=True)
                (destination / 'origin.json').write_text(json.dumps({'original': str(self.directory),
                    'preserved': str(destination), 'kind': 'controlled subprocess evidence, not actual AI'}))
            self.addCleanup(preserve)

    def request(self, operation, payload=None):
        response = self.app.dispatch(operation, payload)
        self.assertTrue(response['ok'], response)
        return response['data']

    def enqueue(self, name):
        profile = self.request('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})
        return self.request('enqueue_run', {'source_path': str(self.source), 'name': name,
            'profile_path': profile['path'], 'profile_sha256': profile['sha256'],
            'environment': os.environ.get('OCR_ENVIRONMENT'), 'defer_corrections': True,
            'request_id': name})

    def wait_queue(self, predicate, timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.request('queue_status')
            if predicate(status):
                return status
            time.sleep(.05)
        self.fail('Queue did not settle: ' + repr(status))

    def hold_peer(self, mode='hold'):
        self.app.close()
        self.peer_state = self.directory / 'provider-state.json'
        self.runtime = {**self.runtime, 'command': [sys.executable, '-B',
            str(ROOT / 'tests/codex_app_server_fixture.py'), mode, str(self.peer_state)]}
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)

    def test_enqueue_reorder_and_restart_preserve_named_runs_without_starting_work(self):
        first, second = self.enqueue('First'), self.enqueue('Second')
        duplicate = self.request('enqueue_run', {'run_id': first['run_id'], 'request_id': 'existing'})
        self.assertEqual(duplicate['item_id'], first['item_id'])
        self.assertEqual(self.enqueue('First')['run_id'], first['run_id'])
        status = self.request('queue_status')
        self.assertEqual(status['state'], 'paused')
        self.assertEqual(status['pending'], [first['item_id'], second['item_id']])
        reordered = self.request('reorder_queue', {'item_ids': list(reversed(status['pending'])),
            'expected_revision': status['revision']})
        stale = self.app.dispatch('reorder_queue', {'item_ids': status['pending'],
            'expected_revision': status['revision']})
        self.assertFalse(stale['ok'])
        self.assertEqual(stale['error']['code'], 'queue_conflict')
        self.assertTrue(any(e['type'] == 'queue_changed' for e in self.request('events')['events']))
        self.app.close()
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        saved = self.request('queue_status')
        self.assertEqual(saved['pending'], reordered['pending'])
        self.assertEqual(saved['state'], 'paused')
        self.assertEqual(len(self.request('projects')['editions'][0]['runs']), 3)  # legacy import + two named runs
        for item in saved['items']:
            self.assertEqual(self.request('autonomous_status', {'run_id': item['run_id']})['state'], 'not_started')

    def test_multiple_editions_follow_changed_order_and_advance_after_bad_pdf_and_open_items(self):
        first = self.enqueue('Open findings')
        self.source.write_bytes(self.source.read_bytes() + b'\n% second edition\n')
        bad = self.enqueue('Broken PDF')
        broken = self.request('select_run', {'run_id': bad['run_id']})
        (self.root / broken['artifacts']['source']['path']).write_bytes(b'broken source')
        self.source.write_bytes(self.source.read_bytes() + b'\n% third edition\n')
        last = self.enqueue('Last edition')
        saved = self.request('queue_status')
        self.request('reorder_queue', {'item_ids': [bad['item_id'], first['item_id'], last['item_id']],
            'expected_revision': saved['revision']})
        before = self.request('projects')
        self.request('resume_queue')
        done = self.wait_queue(lambda q: not q['pending'] and q['active_item_id'] is None)
        self.assertEqual([i['run_id'] for i in sorted(done['items'], key=lambda i: i['started_at'])],
            [bad['run_id'], first['run_id'], last['run_id']])
        outcomes = {i['run_id']: i for i in done['items']}
        self.assertEqual(outcomes[bad['run_id']]['state'], 'failed')
        self.assertEqual(outcomes[bad['run_id']]['reason']['code'], 'source_corrupt')
        self.assertEqual(outcomes[first['run_id']]['state'], 'awaiting_input')
        self.assertEqual(outcomes[last['run_id']]['state'], 'awaiting_input')
        identities = lambda result: sorted((e['edition_id'], sorted(r['run_id'] for r in e['runs'])) for e in result['editions'])
        self.assertEqual(identities(self.request('projects')), identities(before))
        for item in (first, last):
            result = self.request('output_results', {'run_id': item['run_id']})
            self.assertTrue(result['reports']['findings']['items'])
            parent = self.request('autonomous_status', {'run_id': item['run_id']})
            self.assertEqual(parent['queue_item_id'], item['item_id'])

    def test_second_application_process_cannot_admit_manual_stages_or_corrections_during_queue_run(self):
        self.hold_peer()
        active, pending = self.enqueue('Active'), self.enqueue('Pending')
        self.request('resume_queue')
        deadline = time.monotonic() + 30
        while not self.peer_state.exists() and time.monotonic() < deadline:
            time.sleep(.03)
        self.assertTrue(self.peer_state.exists())
        configuration = self.directory / 'other-application.json'
        configuration.write_text(json.dumps({'runtime': self.runtime, 'context': self.context,
            'root': str(self.root), 'run_id': pending['run_id']}))
        script = '''import json,sys
from app.service import Application
c=json.load(open(sys.argv[1]))
a=Application(c['root'],codex_runtime=c['runtime'],context_runtime=c['context'])
try:
 print(json.dumps([a.dispatch(op,{'run_id':c['run_id']}) for op in
 ('start_preparation','start_model_diagnostic','start_context_diagnostic','start_reading',
  'start_geometry','start_output_review','start_corrections')]))
finally: a.close()
'''
        result = subprocess.run([sys.executable, '-B', '-c', script, str(configuration)],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = json.loads(result.stdout)
        self.assertTrue(all(not r['ok'] and r['error']['code'] == 'operation_active' for r in responses), responses)

    def test_typed_global_failures_pause_all_pending_runs_and_keep_original_evidence(self):
        for mode, category in [('queue_auth', 'authentication'), ('queue_model', 'model_unavailable'),
                               ('queue_quota', 'quota'), ('queue_network', 'network')]:
            with self.subTest(mode=mode):
                self.app.close()
                self.root = self.directory / mode
                self.hold_peer(mode)
                first, second = self.enqueue('First'), self.enqueue('Second')
                self.request('resume_queue')
                stopped = self.wait_queue(lambda q: q['state'] == 'blocked', timeout=30)
                self.assertEqual(stopped['reason']['scope'], 'global')
                self.assertEqual(stopped['reason']['category'], category)
                self.assertEqual(stopped['active_item_id'], first['item_id'])
                self.assertEqual(stopped['pending'], [second['item_id']])
                reason = stopped['reason']
                self.assertEqual(reason['run_id'], first['run_id'])
                self.assertTrue(reason['parent_attempt_id'])
                self.assertTrue(reason['child_attempt_id'])
                protocol = self.root / reason['evidence_path']
                self.assertTrue(protocol.is_file())
                if category == 'quota':
                    self.assertEqual(reason['original_error']['codexErrorInfo'], 'usageLimitExceeded')
                    self.assertEqual(reason['turn_id'], 'fixture-turn-13')
                original = protocol.read_bytes()
                self.app.close()
                self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
                after_restart = self.request('queue_status')
                self.assertEqual(after_restart['state'], 'blocked')
                self.assertEqual(after_restart['reason']['category'], category)
                self.request('queue_status')
                self.assertEqual(protocol.read_bytes(), original)
                self.assertEqual(self.request('autonomous_status', {'run_id': second['run_id']})['state'], 'not_started')

    def test_pause_restart_and_explicit_reconciliation_resume_the_same_item_and_wait_metrics(self):
        first, second = self.enqueue('Pause first'), self.enqueue('Pending after pause')
        self.request('resume_queue')
        self.wait_queue(lambda q: q['active_item_id'] == first['item_id'])
        self.request('pause_queue')
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            parent = self.request('autonomous_status', {'run_id': first['run_id']})
            if parent['state'] == 'paused':
                break
            time.sleep(.03)
        self.assertEqual(parent['state'], 'paused', parent)
        self.app.close()
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        saved = self.request('queue_status')
        self.assertEqual(saved['state'], 'paused')
        self.assertEqual(saved['active_item_id'], first['item_id'])
        self.assertEqual(saved['pending'], [second['item_id']])
        rejected = self.app.dispatch('resume_queue')
        self.assertFalse(rejected['ok'])
        identity = {'run_id': first['run_id'], 'attempt_id': parent['attempt_id']}
        proof = self.request('reconcile_autonomous', identity)
        self.request('resume_queue', {'item_id': first['item_id'], **identity,
            'reconciliation_id': proof['reconciliation_id']})
        done = self.wait_queue(lambda q: not q['pending'] and q['active_item_id'] is None)
        resumed = self.request('autonomous_status', {'run_id': first['run_id']})
        self.assertEqual(resumed['attempt_id'], parent['attempt_id'])
        self.assertEqual(len(done['items']), 2)
        metrics = self.request('run_metrics', {'run_id': first['run_id']})
        self.assertGreater(metrics['queue']['waiting_seconds'], 0)
        self.assertTrue(any(i['reason']['code'] == 'operator_paused' for i in metrics['queue']['waiting_intervals']))

    def test_interrupt_unknown_ack_never_replays_after_restart_or_reconciliation(self):
        self.hold_peer('lost_ack')
        first, second = self.enqueue('Unknown delivery'), self.enqueue('Wait for decision')
        self.request('resume_queue')
        deadline = time.monotonic() + 30
        while not self.peer_state.exists() and time.monotonic() < deadline:
            time.sleep(.03)
        self.assertTrue(self.peer_state.exists())
        self.request('interrupt_queue')
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            parent = self.request('autonomous_status', {'run_id': first['run_id']})
            if parent['state'] == 'interrupted':
                break
            time.sleep(.03)
        child = self.request('model_diagnostic_status', {'run_id': first['run_id']})
        protocol = self.root / child['artifacts']['protocol']
        original = protocol.read_bytes()
        self.app.close()
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        saved = self.request('queue_status')
        self.assertEqual(saved['state'], 'paused')
        identity = {'item_id': first['item_id'], 'run_id': first['run_id'], 'attempt_id': parent['attempt_id']}
        proof = self.request('reconcile_autonomous', identity)
        self.assertFalse(proof['provider']['safe_to_continue'])
        rejected = self.app.dispatch('resume_queue', {**identity, 'reconciliation_id': proof['reconciliation_id']})
        self.assertFalse(rejected['ok'], rejected)
        self.assertEqual(rejected['error']['code'], 'reconciliation_required')
        self.assertEqual(protocol.read_bytes(), original)
        outgoing = [json.loads(line) for line in original.splitlines()]
        self.assertEqual(sum(r['direction'] == 'client' and r['message'].get('method') == 'turn/start' for r in outgoing), 1)
        self.assertEqual(self.request('autonomous_status', {'run_id': second['run_id']})['state'], 'not_started')
        manual = self.app.dispatch('start_preparation', {'run_id': second['run_id']})
        self.assertFalse(manual['ok'], manual)
        self.assertEqual(manual['error']['code'], 'reconciliation_required')

    def test_provider_completed_without_local_result_stays_blocked_without_replacement(self):
        self.hold_peer('completed_lost_terminal')
        first, second = self.enqueue('Missing local result'), self.enqueue('Still pending')
        self.request('resume_queue')
        stopped = self.wait_queue(lambda q: q['state'] == 'blocked')
        identity = {'item_id': first['item_id'], 'run_id': first['run_id'],
            'attempt_id': stopped['items'][0]['parent_attempt_id']}
        proof = self.request('reconcile_autonomous', identity)
        self.assertEqual(proof['provider']['turns'][0]['state'], 'completed')
        rejected = self.app.dispatch('resume_queue', {**identity, 'reconciliation_id': proof['reconciliation_id']})
        self.assertFalse(rejected['ok'])
        self.assertEqual(rejected['error']['code'], 'original_result_unavailable')
        self.assertEqual(json.loads(self.peer_state.read_text())['start_count'], 1)
        self.assertEqual(self.request('autonomous_status', {'run_id': second['run_id']})['state'], 'not_started')

    def test_explicit_continue_after_quota_reconciliation_finishes_original_run_and_next_item(self):
        self.app.close()
        state = self.directory / 'quota-backend.json'
        peer = ROOT / 'tests/queue_app_server_fixture.py'
        self.runtime = {**self.runtime, 'command': [sys.executable, '-B', str(peer), str(state)],
            'files': [*self.runtime['files'], {'path': str(peer), 'sha256': hashlib.sha256(peer.read_bytes()).hexdigest()}]}
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        first = self.enqueue('Quota interrupted')
        self.source.write_bytes(self.source.read_bytes() + b'\n% following edition\n')
        second = self.enqueue('Continue next')
        self.source.write_bytes(self.source.read_bytes() + b'\n% bad edition\n')
        bad = self.enqueue('Broken before outage')
        detail = self.request('select_run', {'run_id': bad['run_id']})
        (self.root / detail['artifacts']['source']['path']).write_bytes(b'broken PDF')
        waiting = self.request('queue_status')
        self.request('reorder_queue', {'item_ids': [bad['item_id'], first['item_id'], second['item_id']],
            'expected_revision': waiting['revision']})
        self.request('resume_queue')
        stopped = self.wait_queue(lambda q: q['state'] == 'blocked')
        self.assertEqual(stopped['reason']['category'], 'quota')
        original = self.root / stopped['reason']['evidence_path']
        original_bytes = original.read_bytes()
        Path(str(state) + '.restored').write_text('Explicit controlled provider availability restored')
        identity = {'item_id': first['item_id'], 'run_id': first['run_id'],
            'attempt_id': stopped['items'][0]['parent_attempt_id']}
        proof = self.request('reconcile_autonomous', identity)
        self.assertTrue(proof['provider']['safe_to_continue'])
        self.assertEqual(proof['provider']['turns'][0]['state'], 'failed')
        self.request('resume_queue', {**identity, 'reconciliation_id': proof['reconciliation_id']})
        finished = self.wait_queue(lambda q: not q['pending'] and q['active_item_id'] is None)
        self.assertEqual([i['state'] for i in finished['items']], ['awaiting_input', 'awaiting_input', 'failed'])
        self.assertEqual([i['run_id'] for i in sorted(finished['items'], key=lambda i: i['started_at'])],
            [bad['run_id'], first['run_id'], second['run_id']])
        self.assertEqual(self.request('autonomous_status', {'run_id': first['run_id']})['attempt_id'], identity['attempt_id'])
        self.assertEqual(original.read_bytes(), original_bytes)

    def test_dead_owner_and_surviving_native_child_cannot_be_treated_as_free_execution(self):
        first, second = self.enqueue('Orphan parent'), self.enqueue('Never auto replay')
        self.app.close()
        marker, release = self.directory / 'native-ready.json', self.directory / 'release-native'
        wrapper = self.directory / 'held-native.py'
        wrapper.write_text('import json,os,pathlib,subprocess,sys,time\n'
            'if "prepare" in sys.argv:\n'
            ' pathlib.Path(' + repr(str(marker)) + ').write_text(json.dumps({"pid":os.getpid()}))\n'
            ' deadline=time.monotonic()+30\n'
            ' while not pathlib.Path(' + repr(str(release)) + ').exists() and time.monotonic()<deadline: time.sleep(.03)\n'
            'else:\n'
            ' result=subprocess.run([sys.executable,' + repr(str(ROOT / 'tools/ocr_projects.py')) + ',*sys.argv[1:]],capture_output=True)\n'
            ' sys.stdout.buffer.write(result.stdout);sys.stderr.buffer.write(result.stderr)\n'
            ' raise SystemExit(result.returncode)\n')
        config = self.directory / 'crash-owner.json'
        config.write_text(json.dumps({'root': str(self.root), 'runtime': self.runtime, 'context': self.context,
            'command': [sys.executable, '-B', str(wrapper)], 'marker': str(marker)}))
        code = '''import json,os,pathlib,sys,time
from app.service import Application
c=json.load(open(sys.argv[1]))
a=Application(c['root'],process_command=c['command'],codex_runtime=c['runtime'],context_runtime=c['context'])
assert a.dispatch('resume_queue')['ok']
deadline=time.monotonic()+20
while not pathlib.Path(c['marker']).exists() and time.monotonic()<deadline: time.sleep(.03)
os._exit(0 if pathlib.Path(c['marker']).exists() else 3)
'''
        owner = subprocess.run([sys.executable, '-B', '-c', code, str(config)], cwd=ROOT,
            capture_output=True, text=True, timeout=25)
        self.assertEqual(owner.returncode, 0, owner.stderr)
        child_pid = json.loads(marker.read_text())['pid']
        from app.codex import process_identity
        identity = process_identity(child_pid)
        self.assertIsNotNone(identity)
        try:
            self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
            saved = self.request('queue_status')
            self.assertEqual(saved['state'], 'paused')
            self.assertEqual(saved['active_item_id'], first['item_id'])
            self.assertEqual(saved['pending'], [second['item_id']])
            blocked = self.app.dispatch('start_preparation', {'run_id': second['run_id']})
            self.assertFalse(blocked['ok'])
            self.assertEqual(blocked['error']['code'], 'reconciliation_required')
            self.assertFalse(self.app.dispatch('resume_queue')['ok'])
            self.assertEqual(self.request('autonomous_status', {'run_id': second['run_id']})['state'], 'not_started')
        finally:
            release.write_text('controlled owned native child may exit')
            if process_identity(child_pid) == identity:
                os.killpg(child_pid, signal.SIGTERM)

    def test_lost_enqueue_response_after_native_run_creation_never_creates_a_second_named_run(self):
        profile = self.request('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})
        payload = {'source_path': str(self.source), 'name': 'Lost enqueue response', 'request_id': 'lost-create',
            'profile_path': profile['path'], 'profile_sha256': profile['sha256']}
        self.app.close()
        wrapper = self.directory / 'lose-create-response.py'
        wrapper.write_text('import os,signal,subprocess,sys\n'
            'result=subprocess.run([sys.executable,' + repr(str(ROOT / 'tools/ocr_projects.py')) + ',*sys.argv[1:]],capture_output=True)\n'
            'if any(a.startswith("--run-name=") for a in sys.argv) and result.returncode==0: os.kill(os.getppid(),signal.SIGKILL)\n'
            'sys.stdout.buffer.write(result.stdout);sys.stderr.buffer.write(result.stderr)\n'
            'raise SystemExit(result.returncode)\n')
        config = self.directory / 'lost-enqueue.json'
        config.write_text(json.dumps({'root': str(self.root), 'runtime': self.runtime, 'context': self.context,
            'command': [sys.executable, '-B', str(wrapper)], 'payload': payload}))
        code = '''import json,sys
from app.service import Application
c=json.load(open(sys.argv[1]))
a=Application(c['root'],process_command=c['command'],codex_runtime=c['runtime'],context_runtime=c['context'])
a.dispatch('enqueue_run',c['payload'])
'''
        lost = subprocess.run([sys.executable, '-B', '-c', code, str(config)], cwd=ROOT,
            capture_output=True, text=True, timeout=25)
        self.assertEqual(lost.returncode, -signal.SIGKILL, lost.stderr)
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        before = self.request('projects')
        retried = self.app.dispatch('enqueue_run', payload)
        self.assertFalse(retried['ok'], retried)
        self.assertEqual(retried['error']['code'], 'enqueue_recovery_required')
        self.assertEqual(len(self.request('projects')['editions'][0]['runs']), len(before['editions'][0]['runs']))

    def test_standalone_unknown_delivery_blocks_another_application_and_retains_exact_original(self):
        self.hold_peer('lost_ack')
        first, second = self.enqueue('Standalone unknown'), self.enqueue('Other run')
        from PIL import Image
        image = self.directory / 'manual-image.png'
        Image.new('RGB', (8, 8), 'white').save(image)
        started = self.request('start_model_diagnostic', {'run_id': first['run_id'], 'image_path': str(image)})
        deadline = time.monotonic() + 30
        while not self.peer_state.exists() and time.monotonic() < deadline:
            time.sleep(.03)
        self.assertTrue(self.peer_state.exists())
        # Closing the local transport is not evidence of provider rejection.
        self.app.close()
        original = self.root / started['artifacts']['protocol']
        before = original.read_bytes()
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        manual = self.app.dispatch('start_preparation', {'run_id': second['run_id']})
        self.assertFalse(manual['ok'], manual)
        self.assertEqual(manual['error']['code'], 'reconciliation_required')
        self.request('resume_queue')
        stopped = self.wait_queue(lambda q: q['state'] == 'blocked', timeout=10)
        self.assertEqual(stopped['pending'], [first['item_id'], second['item_id']])
        self.assertIsNone(stopped['active_item_id'])
        evidence = stopped['manual_execution']
        self.assertEqual(evidence['state'], 'reconciliation_required')
        self.assertEqual(evidence['child_attempt_id'], started['attempt_id'])
        self.assertEqual(evidence['failure']['delivery_state'], 'unknown')
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(self.request('autonomous_status', {'run_id': second['run_id']})['state'], 'not_started')

    def test_pending_only_queue_wait_is_incomplete_rather_than_measured_zero(self):
        item = self.enqueue('Waiting without an end')
        metrics = self.request('run_metrics', {'run_id': item['run_id']})
        self.assertIsNone(metrics['queue']['waiting_seconds'])
        self.assertEqual(metrics['queue']['status'], 'partial')
        self.assertIsNone(metrics['queue']['waiting_intervals'][0]['end'])

    def test_changed_ai_pin_before_parent_launch_blocks_queue_and_explicit_restore_can_continue(self):
        self.app.close()
        pin = self.directory / 'controlled-runtime-pin.py'
        pin.write_text('# controlled runtime pin\n')
        original_pin = pin.read_bytes()
        self.runtime = {**self.runtime, 'files': [*self.runtime['files'], {'path': str(pin),
            'sha256': hashlib.sha256(original_pin).hexdigest()}]}
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        first, second = self.enqueue('Cannot launch'), self.enqueue('Keep pending')
        pin.write_text('# changed controlled fixture, never the inventoried runtime\n')
        self.request('resume_queue')
        stopped = self.wait_queue(lambda q: q['state'] == 'blocked' or not q['pending'] and q['active_item_id'] is None)
        self.assertEqual(stopped['state'], 'blocked')
        self.assertEqual(stopped['reason']['code'], 'runtime_changed')
        self.assertEqual(stopped['reason']['category'], 'ai_unavailable')
        self.assertEqual(stopped['pending'], [second['item_id']])
        self.assertEqual(stopped['active_item_id'], first['item_id'])
        self.assertEqual(self.request('autonomous_status', {'run_id': first['run_id']})['state'], 'not_started')
        self.app.close()
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        self.assertEqual(self.request('queue_status')['reason']['code'], 'runtime_changed')
        pin.write_bytes(original_pin)
        saved_first = next(i for i in stopped['items'] if i['item_id'] == first['item_id'])
        self.request('resume_queue', {'item_id': first['item_id'], 'run_id': first['run_id'],
            'attempt_id': saved_first['parent_attempt_id']})
        self.request('pause_queue')
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            parent = self.request('autonomous_status', {'run_id': first['run_id']})
            if parent['state'] == 'paused':
                break
            time.sleep(.03)
        self.assertEqual(parent['state'], 'paused', parent)
        self.assertEqual(parent['attempt_id'], saved_first['parent_attempt_id'])

    def test_queue_waiting_on_foreign_execution_cannot_switch_away_from_its_registry(self):
        first = self.enqueue('Wait for foreign owner')
        ready, release = self.directory / 'foreign-ready', self.directory / 'release-foreign'
        wrapper = self.directory / 'foreign-native.py'
        wrapper.write_text('import pathlib,subprocess,sys,time\n'
            'if "prepare" in sys.argv:\n'
            ' pathlib.Path(' + repr(str(ready)) + ').write_text("held")\n'
            ' deadline=time.monotonic()+15\n'
            ' while not pathlib.Path(' + repr(str(release)) + ').exists() and time.monotonic()<deadline: time.sleep(.03)\n'
            'else:\n'
            ' result=subprocess.run([sys.executable,' + repr(str(ROOT / 'tools/ocr_projects.py')) + ',*sys.argv[1:]],capture_output=True)\n'
            ' sys.stdout.buffer.write(result.stdout);sys.stderr.buffer.write(result.stderr)\n'
            ' raise SystemExit(result.returncode)\n')
        foreign = Application(self.root, process_command=[sys.executable, '-B', str(wrapper)],
            codex_runtime=self.runtime, context_runtime=self.context)
        self.addCleanup(foreign.close)
        try:
            started = foreign.dispatch('start_preparation', {'run_id': first['run_id']})
            self.assertTrue(started['ok'], started)
            deadline = time.monotonic() + 10
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(.03)
            self.assertTrue(ready.exists())
            self.request('resume_queue')
            waiting = self.request('queue_status')
            self.assertIsNone(waiting['active_item_id'])
            self.assertEqual(waiting['state'], 'running')
            another = self.directory / 'another-registry'
            another.mkdir()
            switched = self.app.dispatch('open_registry', {'root': str(another)})
            self.assertFalse(switched['ok'], switched)
            self.assertEqual(switched['error']['code'], 'operation_active')
            self.assertEqual(self.request('queue_status')['root'], str(self.root))
        finally:
            self.request('pause_queue')
            release.write_text('release controlled owner')


if __name__ == '__main__':
    unittest.main()
