"""Public crash recovery of an explicitly allowed, never submitted successor."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest

from app.service import Application
import test_webui_export as export_tests

ROOT = Path(__file__).resolve().parents[1]
PROOF = Path(os.environ.get('OCR_RELEASE_PROOF', ROOT / '.scratch/ticket-23-proof/presubmit-recovery'))


class PresubmitRecoveryTests(unittest.TestCase):
    setUp = export_tests.AutonomousExportTests.setUp

    def wait(self, call, identity):
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            result = call('autonomous_status', identity)
            self.assertTrue(result['ok'], result)
            if result['data']['state'] not in ('starting', 'running', 'pausing', 'interrupting'):
                return result['data']
            time.sleep(.03)
        self.fail('Public action did not settle: ' + repr(result))

    def test_repair_reserved_directory_recovers_exact_successor_edge(self):
        self.scenario('repair', 'directory')

    def test_repair_submission_intent_recovers_without_rewriting_original_request(self):
        self.scenario('repair', 'intent')

    def test_output_reserved_directory_recovers_exact_successor_edge(self):
        self.scenario('output', 'directory')

    def test_output_submission_intent_recovers_without_rewriting_original_request(self):
        self.scenario('output', 'intent')

    def test_unknown_repair_successor_cannot_replay_its_reserved_request(self):
        self.scenario('repair', 'intent', delivery='unknown')

    def test_accepted_output_successor_cannot_replay_its_reserved_request(self):
        self.scenario('output', 'intent', delivery='accepted')

    def scenario(self, stage, boundary, *, delivery=None):
        self.app.close()
        source_bytes = self.source.read_bytes()
        marker = self.directory / 'provider-rejection'
        peer = ROOT / 'tests/presubmit_provider_fixture.py'
        wrapper = self.directory / 'provider.py'
        wrapper.write_text('import os,runpy\nos.environ["PRESUBMIT_STAGE"]=' + repr(stage) +
            '\nos.environ["PRESUBMIT_MARKER"]=' + repr(str(marker)) + '\nrunpy.run_path(' + repr(str(peer)) + ',run_name="__main__")\n')
        files = [peer, wrapper, ROOT / 'tests/corrections_app_server_fixture.py']
        self.runtime = {**self.runtime, 'command': [sys.executable, '-B', str(wrapper)],
            'files': [*self.runtime['files'], *[{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]]}
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        process = None
        def preserve():
            self.app.close()
            if process is not None:
                if process.poll() is None:
                    process.terminate(); process.wait(timeout=10)
                process.stdin.close(); process.stdout.close()
            destination = PROOF / (self._testMethodName + '-' + str(time.time_ns()))
            mappings = [{'original': str(p), 'copied': str(destination / p.relative_to(self.directory)),
                'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'mode': p.stat().st_mode & 0o7777}
                for p in self.directory.rglob('*') if p.is_file()]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.directory, destination)
            (destination / 'origin-mapping.json').write_text(json.dumps(mappings, indent=2))
        self.addCleanup(preserve)
        profile = ROOT / 'profiles/faithful-reading.json'
        payload = {'source_path': str(self.source), 'name': 'Presubmit recovery', 'profile_path': str(profile),
            'profile_sha256': hashlib.sha256(profile.read_bytes()).hexdigest(), 'environment': os.environ.get('OCR_ENVIRONMENT')}
        started = self.app.dispatch('start_autonomous', payload)
        self.assertTrue(started['ok'], started)
        identity = {k: started['data'][k] for k in ('run_id', 'attempt_id')}
        self.assertEqual(self.wait(self.app.dispatch, identity)['state'], 'failed')
        before = self.app.dispatch('correction_status', identity)['data']
        detail = self.app.dispatch('select_run', identity)['data']
        work = self.root / detail['artifacts']['workspace']['path']
        correction_path = work / 'application/correction-attempts' / before['attempt_id'] / 'attempt.json'
        if stage == 'repair':
            attempt_path = correction_path
        else:
            attempt_path = work / 'application/output-review-attempts' / json.loads(correction_path.read_text())['children'][-1]['attempt_id'] / 'attempt.json'
        original_attempt = json.loads(attempt_path.read_text())
        visual_stage = 'repair_1' if stage == 'repair' else 'output_examination'
        original_protocol = attempt_path.parent / visual_stage / 'protocol.jsonl'
        original_bytes = original_protocol.read_bytes()
        pixels = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (work / 'raster').glob('*.png')}
        self.assertTrue(pixels)
        checked = self.app.dispatch('reconcile_autonomous', identity)
        self.assertTrue(checked['ok'], checked)
        self.assertTrue(checked['data']['provider']['safe_to_continue'], checked)
        Path(str(marker) + '.restored').touch()
        self.app.close()
        runtime, context = self.directory / 'runtime.json', self.directory / 'context.json'
        runtime.write_text(json.dumps(self.runtime)); context.write_text(json.dumps(self.context))
        crash = self.directory / 'crash.json'
        stderr = (self.directory / 'owner.stderr').open('wb'); self.addCleanup(stderr.close)
        process = subprocess.Popen([sys.executable, '-B', str(ROOT / 'tests/presubmit_application_fixture.py'),
            str(self.root), str(runtime), str(context), str(crash), boundary],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr)
        def call(operation, data):
            process.stdin.write((json.dumps({'operation': operation, 'payload': data}) + '\n').encode()); process.stdin.flush()
            return json.loads(process.stdout.readline())
        resumed = call('resume_autonomous', {**identity, 'reconciliation_id': checked['data']['reconciliation_id']})
        self.assertTrue(resumed['ok'], resumed)
        process.wait(timeout=150)
        self.assertEqual(process.returncode, 91)
        stopped = json.loads(attempt_path.read_text())
        reservation = stopped['continuations'][-1]
        self.assertIsNone(reservation['successor'])
        physical = Path(json.loads(crash.read_text())['directory'])
        self.assertEqual(str(physical.relative_to(self.root)), reservation['directory'])
        intent_bytes = {str(p): p.read_bytes() for p in (Path(reservation['intent']['path']), physical / 'submission-intent.json', physical / 'request.json') if p.exists()}
        self.assertEqual((physical / 'submission-intent.json').exists(), boundary == 'intent')
        if delivery:
            Path(str(marker) + '.delivery').write_text(delivery)
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        checked = self.app.dispatch('reconcile_autonomous', identity)
        self.assertTrue(checked['ok'], checked)
        self.assertTrue(checked['data']['provider']['safe_to_continue'], checked)
        resumed = self.app.dispatch('resume_autonomous', {**identity, 'reconciliation_id': checked['data']['reconciliation_id']})
        self.assertTrue(resumed['ok'], resumed)
        self.assertEqual(self.wait(self.app.dispatch, identity)['state'], 'failed' if delivery else 'completed')
        after = json.loads(attempt_path.read_text())
        self.assertEqual(after['attempt_id'], original_attempt['attempt_id'])
        self.assertEqual(after['parent_binding'], original_attempt['parent_binding'])
        self.assertEqual(len(after['continuations']), 1)
        successor = after['continuations'][0]['successor']
        self.assertIsNotNone(successor, 'Allowed successor must retain its immutable reservation edge')
        self.assertEqual(successor['state'], 'accepted' if delivery == 'accepted' else 'not_submitted' if delivery else 'completed')
        self.assertEqual(Path(successor['protocol']['path']).parent, physical)
        for path, data in intent_bytes.items():
            self.assertEqual(Path(path).read_bytes(), data)
        self.assertEqual(original_protocol.read_bytes(), original_bytes)
        for path, digest in pixels.items():
            self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(), digest)
        self.assertEqual(self.source.read_bytes(), source_bytes)
        ledger = self.app.dispatch('correction_status', identity)['data']
        self.assertEqual(ledger['cycles_used'], 1)
        self.assertEqual(ledger['cycles'][0]['cycle_id'], before['cycles'][0]['cycle_id'])
        self.assertEqual(self.app.dispatch('autonomous_status', identity)['data']['attempt_id'], identity['attempt_id'])
        if delivery:
            native = {p: p.read_bytes() for p in (attempt_path.parent / 'protocol.jsonl', Path(successor['protocol']['path']))}
            checked = self.app.dispatch('reconcile_autonomous', identity)
            self.assertTrue(checked['ok'], checked)
            self.assertFalse(checked['data']['provider']['safe_to_continue'], checked)
            denied = self.app.dispatch('resume_autonomous', {**identity, 'reconciliation_id': checked['data']['reconciliation_id']})
            self.assertFalse(denied['ok'], denied)
            self.assertEqual(denied['error']['code'], 'reconciliation_required')
            for p, data in native.items():
                self.assertEqual(p.read_bytes(), data)
        # The artifact classifier is a read-only reader of the original native
        # journals. Reconciliation itself is intentionally unavailable once done.
        from app.failures import run_failure
        classified = run_failure(self.root, self.app.dispatch('select_run', identity)['data'],
            self.app.dispatch('autonomous_status', identity)['data'])
        if stage == 'output':
            classified = next(row for row in classified['descendants'] if row['child_attempt_id'] == after['attempt_id'])
        submissions = [r for r in classified['submissions'] if r.get('visual_stage') == visual_stage]
        self.assertEqual(len(submissions), 2, submissions)
        rejected = next(r for r in submissions if r['delivery_state'] == 'rejected')
        if delivery:
            self.assertFalse(rejected.get('resolved_by'), rejected)
            self.assertEqual(submissions[-1]['delivery_state'], delivery)
        else:
            self.assertTrue(rejected['resolved_by'], rejected)
        frames = [json.loads(line) for line in Path(successor['protocol']['path']).read_text().splitlines()]
        starts = [r for r in frames if r['direction'] == 'client' and r['message'].get('method') == 'turn/start']
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0]['connection_id'], successor['connection_id'])
        original_start = next(json.loads(line) for line in original_bytes.splitlines() if json.loads(line)['message'].get('method') == 'turn/start')
        self.assertEqual(starts[0]['message']['params']['input'], original_start['message']['params']['input'])


if __name__ == '__main__':
    unittest.main()
