"""Public combined-action recovery; controlled provider, real native artifacts."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest

import test_webui_export as export_tests
from app.service import Application

ROOT = Path(__file__).resolve().parents[1]
PROOF = Path(os.environ.get('OCR_RELEASE_PROOF', ROOT / '.scratch/ticket-23-proof')) / 'correction-recovery'


class ReleaseRecoveryTests(unittest.TestCase):
    setUp = export_tests.AutonomousExportTests.setUp

    def wait(self, run_id):
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            result = self.app.dispatch('autonomous_status', {'run_id': run_id})
            self.assertTrue(result['ok'], result)
            if result['data']['state'] not in ('starting', 'running', 'pausing', 'interrupting'):
                return result['data']
            time.sleep(.03)
        self.fail('Combined action did not settle: ' + repr(result))

    def test_resume_after_published_repair_keeps_parent_child_cycle_and_original_turn(self):
        self.resume_scenario('publish-correction')

    def test_retired_ancestor_protocol_and_proposal_resolve_only_by_exact_snapshot_catalog(self):
        self.resume_scenario('publish-correction', retire_ancestor=True)

    def test_resume_after_committed_export_adopts_same_iteration_without_new_geometry_turn(self):
        self.resume_scenario('export')

    def test_resume_after_export_intent_keeps_the_reserved_iteration_uuid(self):
        self.resume_scenario('prepare-correction-export')

    def test_resume_after_render_before_export_commit_adopts_exact_rendered_bytes(self):
        self.resume_scenario('render-correction-export')

    def test_resume_keeps_the_original_cycle_bound_output_review_child(self):
        self.resume_scenario('output-child')

    def test_owner_crash_before_output_link_recovers_the_already_bound_child(self):
        self.owner_crash_scenario('output-link')

    def test_native_crash_after_raw_render_before_manifest_binding_recovers_the_same_bytes(self):
        self.owner_crash_scenario('render-manifest')

    def test_native_crash_before_exported_ledger_commit_keeps_the_same_final_bytes(self):
        self.owner_crash_scenario('export-ledger')

    def test_native_crash_after_exported_ledger_before_project_commit_keeps_same_iteration(self):
        self.owner_crash_scenario('export-project')

    def test_completed_original_repair_survives_owner_crash_before_publication_without_replay(self):
        self.owner_crash_scenario('repair-publication')

    def test_completed_original_geometry_survives_owner_crash_before_checkpoint_without_replay(self):
        self.owner_crash_scenario('geometry-publication')

    def test_native_crash_after_patch_before_cycle_commit_adopts_original_patch_without_new_snapshot(self):
        self.owner_crash_scenario('patch-ledger')

    def test_native_crash_during_patch_metadata_commit_finishes_only_missing_transaction_writes(self):
        self.owner_crash_scenario('patch-chain')

    def test_native_crash_after_outcome_before_ledger_adopts_original_result_without_revalidation(self):
        self.owner_crash_scenario('outcome-ledger')

    def test_rejected_global_repair_keeps_cycle_blocks_new_parent_and_explicitly_continues_original(self):
        self.app.close()
        peer = ROOT / 'tests/corrections_app_server_fixture.py'
        marker = self.directory / 'repair-quota-rejection'
        wrapper = self.directory / 'quota-repair-peer.py'
        wrapper.write_text('import os,runpy,sys\nos.environ["RELEASE_REPAIR_REJECT"]=' + repr(str(marker)) +
            '\nsys.argv.insert(1,"repair")\nrunpy.run_path(' + repr(str(peer)) + ',run_name="__main__")\n')
        self.runtime = {**self.runtime, 'command': [sys.executable, '-B', str(wrapper)],
            'files': [*self.runtime['files'], *[{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in (peer, wrapper)]]}
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        def preserve():
            self.app.close()
            destination = PROOF / (self._testMethodName + '-' + str(time.time_ns()))
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.directory, destination)
        self.addCleanup(preserve)
        profile = ROOT / 'profiles/faithful-reading.json'
        payload = {'source_path': str(self.source), 'name': 'Original quota rejected repair',
            'profile_path': str(profile), 'profile_sha256': hashlib.sha256(profile.read_bytes()).hexdigest(),
            'environment': os.environ.get('OCR_ENVIRONMENT')}
        started = self.app.dispatch('start_autonomous', payload)
        self.assertTrue(started['ok'], started)
        identity = {key: started['data'][key] for key in ('run_id', 'attempt_id')}
        self.assertEqual(self.wait(identity['run_id'])['state'], 'failed')
        self.assertTrue(marker.is_file())
        before = self.app.dispatch('correction_status', identity)['data']
        self.assertEqual(before['cycles_used'], 1)
        self.assertEqual(before['cycles'][0]['state'], 'reserved', before)
        self.assertIsNone(before['stop_reason'], before)
        detail = self.app.dispatch('select_run', identity)['data']
        work = self.root / detail['artifacts']['workspace']['path']
        protocol = work / 'application/correction-attempts' / before['attempt_id'] / 'repair_1/protocol.jsonl'
        original = protocol.read_bytes()
        self.app.close()
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        denied = self.app.dispatch('start_autonomous', {**payload, 'name': 'Do not replace the globally rejected parent'})
        self.assertFalse(denied['ok'], denied)
        self.assertEqual(denied['error']['code'], 'reconciliation_required')
        self.assertEqual(len(list((self.root / 'work').glob('*/application/autonomous-attempts/*/attempt.json'))), 1)
        checked = self.app.dispatch('reconcile_autonomous', identity)
        self.assertTrue(checked['ok'], checked)
        self.assertTrue(checked['data']['checkpoint']['valid'], checked)
        self.assertTrue(checked['data']['provider']['safe_to_continue'], checked)
        self.assertEqual(checked['data']['provider']['turns'][-1]['state'], 'rejected')
        Path(str(marker) + '.restored').write_text('Explicitly restored controlled provider; no automatic retry')
        resumed = self.app.dispatch('resume_autonomous', {**identity, 'reconciliation_id': checked['data']['reconciliation_id']})
        self.assertTrue(resumed['ok'], resumed)
        self.assertEqual(self.wait(identity['run_id'])['state'], 'completed')
        self.assertEqual(protocol.read_bytes(), original)
        after = self.app.dispatch('correction_status', identity)['data']
        self.assertEqual(after['attempt_id'], before['attempt_id'])
        self.assertEqual(after['cycles_used'], 1)
        self.assertEqual(after['cycles'][0]['cycle_id'], before['cycles'][0]['cycle_id'])
        frames = [json.loads(line) for line in protocol.parent.parent.joinpath('protocol.jsonl').read_text().splitlines()]
        repair_starts = [row for row in frames if row['stage'] == 'repair_1' and row['direction'] == 'client' and row['message'].get('method') == 'turn/start']
        self.assertEqual(len(repair_starts), 2)
        self.assertNotEqual(repair_starts[0]['connection_id'], repair_starts[1]['connection_id'])
        self.assertEqual(repair_starts[0]['message']['params']['input'], repair_starts[1]['message']['params']['input'])
        history = self.app.dispatch('select_run', identity)['data']['history']
        continuation = [row for row in history if row['type'] == 'correction_continuation_reserved']
        self.assertEqual(len(continuation), 1)
        self.assertEqual(continuation[0]['cycle_id'], before['cycles'][0]['cycle_id'])
        self.assertEqual(continuation[0]['original_delivery'], 'rejected')

    def test_unknown_repair_delivery_keeps_reserved_budget_and_cannot_replay(self):
        self.app.close()
        peer = ROOT / 'tests/corrections_app_server_fixture.py'
        marker = self.directory / 'repair-delivery-unknown'
        wrapper = self.directory / 'unknown-repair-peer.py'
        wrapper.write_text('import os,runpy,sys\nos.environ["RELEASE_REPAIR_LOST_ACK"]=' + repr(str(marker)) +
            '\nsys.argv.insert(1,"repair")\nrunpy.run_path(' + repr(str(peer)) + ',run_name="__main__")\n')
        self.runtime = {**self.runtime, 'command': [sys.executable, '-B', str(wrapper)],
            'files': [*self.runtime['files'], *[{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in (peer, wrapper)]]}
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        def preserve():
            self.app.close()
            destination = PROOF / (self._testMethodName + '-' + str(time.time_ns()))
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.directory, destination)
        self.addCleanup(preserve)
        profile = ROOT / 'profiles/faithful-reading.json'
        started = self.app.dispatch('start_autonomous', {'source_path': str(self.source),
            'name': 'Unknown original repair delivery', 'profile_path': str(profile),
            'profile_sha256': hashlib.sha256(profile.read_bytes()).hexdigest(),
            'environment': os.environ.get('OCR_ENVIRONMENT')})
        self.assertTrue(started['ok'], started)
        identity = {key: started['data'][key] for key in ('run_id', 'attempt_id')}
        self.assertEqual(self.wait(identity['run_id'])['state'], 'failed')
        self.assertTrue(marker.is_file())
        correction = self.app.dispatch('correction_status', identity)['data']
        detail = self.app.dispatch('select_run', identity)['data']
        work = self.root / detail['artifacts']['workspace']['path']
        protocol = work / 'application/correction-attempts' / correction['attempt_id'] / 'protocol.jsonl'
        original = protocol.read_bytes()
        self.app.close()
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        checked = self.app.dispatch('reconcile_autonomous', identity)
        self.assertTrue(checked['ok'], checked)
        self.assertEqual(checked['data']['provider']['state'], 'unknown')
        self.assertFalse(checked['data']['provider']['safe_to_continue'])
        denied = self.app.dispatch('resume_autonomous', {**identity, 'reconciliation_id': checked['data']['reconciliation_id']})
        self.assertFalse(denied['ok'], denied)
        self.assertEqual(denied['error']['code'], 'reconciliation_required')
        manual = self.app.dispatch('start_model_diagnostic', identity)
        self.assertFalse(manual['ok'], manual)
        self.assertEqual(manual['error']['code'], 'reconciliation_required')
        self.assertEqual(protocol.read_bytes(), original)
        starts = [json.loads(line) for line in original.splitlines()]
        self.assertEqual(sum(row['direction'] == 'client' and row['message'].get('method') == 'turn/start' for row in starts), 1)
        retained = self.app.dispatch('correction_status', identity)['data']
        self.assertEqual(retained['attempt_id'], correction['attempt_id'])
        self.assertEqual(retained['cycles_used'], 1)
        self.assertEqual(retained['cycles'][0]['cycle_id'], correction['cycles'][0]['cycle_id'])
        self.assertEqual(retained['cycles'][0]['state'], 'reserved', retained)
        self.assertIsNone(retained['stop_reason'], retained)

    def owner_crash_scenario(self, fault_mode):
        self.app.close()
        peer = ROOT / 'tests/corrections_app_server_fixture.py'
        wrapper = self.directory / 'repair-peer.py'
        wrapper.write_text('import runpy,sys\nsys.argv.insert(1,"repair")\nrunpy.run_path(' + repr(str(peer)) + ',run_name="__main__")\n')
        self.runtime = {**self.runtime, 'command': [sys.executable, '-B', str(wrapper)],
            'files': [*self.runtime['files'], *[{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in (peer, wrapper)]]}
        runtime, context = self.directory / 'runtime.json', self.directory / 'context.json'
        runtime.write_text(json.dumps(self.runtime)); context.write_text(json.dumps(self.context))
        marker = self.directory / 'crash-boundary.json'
        stderr = (self.directory / 'owner-stderr.log').open('wb')
        self.addCleanup(stderr.close)
        process = subprocess.Popen([sys.executable, '-B', str(ROOT / 'tests/application_process_fixture.py'),
            str(self.root), str(runtime), str(context), str(marker), fault_mode], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr)
        def preserve():
            self.app.close()
            if process.poll() is None:
                process.terminate(); process.wait(timeout=5)
            process.stdin.close(); process.stdout.close()
            destination = PROOF / (self._testMethodName + '-' + str(time.time_ns()))
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.directory, destination)
        self.addCleanup(preserve)
        profile = ROOT / 'profiles/faithful-reading.json'
        process.stdin.write((json.dumps({'operation': 'start_autonomous', 'payload': {
            'source_path': str(self.source), 'name': 'Original output child crash recovery',
            'profile_path': str(profile), 'profile_sha256': hashlib.sha256(profile.read_bytes()).hexdigest(),
            'environment': os.environ.get('OCR_ENVIRONMENT')}}) + '\n').encode())
        process.stdin.flush()
        started = json.loads(process.stdout.readline())
        self.assertTrue(started['ok'], started)
        identity = {key: started['data'][key] for key in ('run_id', 'attempt_id')}
        deadline = time.monotonic() + 120
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(.03)
        visual_publication = fault_mode in ('repair-publication', 'geometry-publication')
        self.assertEqual(process.poll(), 91 if fault_mode == 'output-link' or visual_publication else -9,
            (marker.exists(), (self.directory / 'owner-stderr.log').read_text()[-1000:]))
        crashed = json.loads(marker.read_text())
        self.app = Application(self.root, codex_runtime=self.runtime, context_runtime=self.context)
        detail = self.app.dispatch('select_run', identity)['data']
        work = self.root / detail['artifacts']['workspace']['path']
        child_path = work / 'application/correction-attempts' / crashed['correction_attempt_id'] / 'attempt.json'
        old_correction = json.loads(child_path.read_text())
        original_turns = old_correction['turns']
        original_visual_reuse = visual_publication or fault_mode in ('patch-ledger', 'patch-chain')
        original_visual = Path(crashed['original_visual_turn']['protocol']['path']).read_bytes() if original_visual_reuse else None
        if fault_mode == 'outcome-ledger':
            self.assertEqual(len(old_correction['children']), 1)
        else:
            self.assertFalse(old_correction.get('children'))
        self.assertEqual(hashlib.sha256(child_path.read_bytes()).hexdigest(), crashed['original_parent_manifest_sha256'])
        checked = self.app.dispatch('reconcile_autonomous', identity)
        self.assertTrue(checked['ok'], checked)
        self.assertTrue(checked['data']['checkpoint']['valid'], checked)
        resumed = self.app.dispatch('resume_autonomous', {**identity, 'reconciliation_id': checked['data']['reconciliation_id']})
        self.assertTrue(resumed['ok'], resumed)
        complete = self.wait(identity['run_id'])
        self.assertEqual(complete['state'], 'completed', complete)
        correction = self.app.dispatch('correction_status', identity)['data']
        self.assertEqual(correction['attempt_id'], crashed['correction_attempt_id'])
        self.assertEqual(correction['cycles_used'], 1)
        self.assertEqual(correction['cycles'][0]['cycle_id'], crashed['cycle_id'])
        output = self.app.dispatch('output_review_status', identity)['data']
        if fault_mode == 'outcome-ledger':
            self.assertEqual(output['attempt_id'], crashed['output_attempt_id'])
            self.assertEqual(hashlib.sha256((work / correction['cycles'][0]['outcome']).read_bytes()).hexdigest(), crashed['outcome_sha256'])
            self.assertEqual(hashlib.sha256((work / 'checks/run-validation.json').read_bytes()).hexdigest(), crashed['validation_sha256'])
            history = self.app.dispatch('select_run', identity)['data']['history']
            self.assertEqual(sum(row['type'] == 'correction_validation_started' for row in history), 1)
        if fault_mode == 'output-link':
            self.assertEqual(output['attempt_id'], crashed['output_attempt_id'])
        elif not original_visual_reuse:
            manifest = json.loads((work / 'output-manifest.json').read_text())
            self.assertEqual(manifest['iteration_id'], crashed['iteration_id'])
            self.assertEqual(manifest['pdf_sha256'], crashed['rendered_pdf_sha256'])
            self.assertEqual(manifest['txt_sha256'], crashed['rendered_txt_sha256'])
        if original_visual_reuse:
            self.assertEqual(Path(crashed['original_visual_turn']['protocol']['path']).read_bytes(), original_visual)
            frames = [json.loads(line) for line in original_visual.splitlines()]
            self.assertEqual(sum(row['direction'] == 'client' and row['message'].get('method') == 'turn/start' for row in frames), 1)
            phase = 'geometry_1' if fault_mode == 'geometry-publication' else 'repair_1'
            repaired = [turn for turn in json.loads(child_path.read_text())['turns'] if turn['stage'] == phase]
            self.assertEqual(len(repaired), 1)
            self.assertEqual(repaired[0]['turn_id'], crashed['original_visual_turn']['turn_id'])
            if fault_mode in ('patch-ledger', 'patch-chain'):
                self.assertEqual(correction['cycles'][0]['previous_snapshot'], crashed['previous_snapshot'])
                self.assertEqual(hashlib.sha256((work / 'review.json').read_bytes()).hexdigest(), crashed['review_sha256'])
                self.assertEqual(len(list((work / 'iterations').glob('*/snapshot.json'))), 1)
                if fault_mode == 'patch-chain':
                    self.assertTrue(crashed['metadata_not_committed'])
        else:
            self.assertEqual(json.loads(child_path.read_text())['turns'], original_turns)
        self.assertEqual(len(list((work / 'application/output-review-attempts').glob('*/attempt.json'))), 2)
        self.assertEqual(output['parent_binding']['cycle_id'], crashed['cycle_id'])

    def resume_scenario(self, gate, *, retire_ancestor=False):
        self.app.close()
        ready, release = self.directory / 'patch-published', self.directory / 'release-patch'
        native = self.directory / 'native-gate.py'
        native.write_text('import json,pathlib,subprocess,sys,time\n'
            'r=subprocess.run([sys.executable,"-B",' + repr(str(ROOT / 'tools/ocr_projects.py')) + ',*sys.argv[1:]],capture_output=True)\n'
            'opindex=sys.argv.index("--json")+1\noperation=sys.argv[opindex]\n'
            'work=pathlib.Path(sys.argv[sys.argv.index("--root")+1])/"work"/sys.argv[opindex+1]\n'
            'ledger=work/"application/corrections/ledger.json"\n'
            'correction=ledger.is_file() and json.loads(ledger.read_text())["cycles"][-1]["state"]=="published"\n'
            'target=(operation in ("prepare-output-review","verify-output-preparation") and len(list((work/"application/output-review-attempts").glob("*/attempt.json")))>=2) if ' + repr(gate == 'output-child') + ' else operation==' + repr(gate) + '\n'
            'if target and r.returncode==0 and correction:\n'
            ' pathlib.Path(' + repr(str(ready)) + ').touch()\n'
            ' while not pathlib.Path(' + repr(str(release)) + ').exists(): time.sleep(.01)\n'
            'sys.stdout.buffer.write(r.stdout)\nsys.stderr.buffer.write(r.stderr)\n'
            'raise SystemExit(r.returncode)\n')
        peer = ROOT / 'tests/corrections_app_server_fixture.py'
        wrapper = self.directory / 'repair-peer.py'
        wrapper.write_text('import runpy,sys\nsys.argv.insert(1,"repair")\nrunpy.run_path(' + repr(str(peer)) + ',run_name="__main__")\n')
        self.runtime = {**self.runtime, 'command': [sys.executable, '-B', str(wrapper)],
            'files': [*self.runtime['files'], *[{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in (peer, wrapper)]]}
        self.app = Application(self.root, process_command=[sys.executable, '-B', str(native)],
            codex_runtime=self.runtime, context_runtime=self.context)
        def preserve():
            self.app.close()
            destination = PROOF / (self._testMethodName + '-' + str(time.time_ns()))
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.directory, destination)
        self.addCleanup(preserve)
        profile = self.app.dispatch('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})['data']
        started = self.app.dispatch('start_autonomous', {'source_path': str(self.source), 'name': 'Release correction recovery',
            'profile_path': profile['path'], 'profile_sha256': profile['sha256'],
            'environment': os.environ.get('OCR_ENVIRONMENT')})
        self.assertTrue(started['ok'], started)
        identity = {key: started['data'][key] for key in ('run_id', 'attempt_id')}
        deadline = time.monotonic() + 100
        while not ready.exists() and time.monotonic() < deadline:
            state = self.app.dispatch('autonomous_status', identity)
            if state['ok'] and state['data']['state'] not in ('starting', 'running'):
                self.fail('Combined action did not reach the requested native phase: ' + repr(state['data'].get('error')))
            time.sleep(.03)
        self.assertTrue(ready.exists(), self.app.dispatch('autonomous_status', identity))
        paused = self.app.dispatch('pause_autonomous', identity)
        release.touch()
        self.assertTrue(paused['ok'], paused)
        self.assertEqual(self.wait(identity['run_id'])['state'], 'paused')
        before = self.app.dispatch('correction_status', identity)['data']
        self.assertEqual(before['cycles_used'], 1, before)
        detail = self.app.dispatch('select_run', identity)['data']
        work = self.root / detail['artifacts']['workspace']['path']
        archived = {str(p.relative_to(work)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (work / 'iterations').rglob('*') if p.is_file()}
        original = work / 'application/correction-attempts' / before['attempt_id'] / 'attempt.json'
        original_turns = json.loads(original.read_text())['turns']
        if retire_ancestor:
            previous = work / before['cycles'][0]['previous_snapshot']
            checkpoint = json.loads((previous / 'geometry-checkpoint.json').read_text())
            pointers = [checkpoint['visual_turn']['protocol'], checkpoint['evidence']['proposal']]
            inventory = self.directory / 'retired-ancestor-inputs.json'
            inventory.write_text(json.dumps({'records': [{'original_path': item['path'], 'sha256': item['sha256'],
                'kind': 'whole_file', 'source': {'path': str(previous / Path(item['path']).relative_to(work))},
                'proof': {'native_snapshot': str(previous / 'snapshot.json'),
                    'native_snapshot_sha256': hashlib.sha256((previous / 'snapshot.json').read_bytes()).hexdigest()}}
                for item in pointers]}))
            archive = self.directory / 'retired-ancestor-archive'
            captured = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/ocr_evidence_archive.py'),
                'capture', '--inventory', str(inventory), '--output', str(archive)], capture_output=True, text=True)
            self.assertEqual(captured.returncode, 0, captured.stderr + captured.stdout)
            old_catalog = os.environ.get('OCR_EVIDENCE_CATALOG')
            os.environ['OCR_EVIDENCE_CATALOG'] = str(archive / 'catalog.json')
            def restore_catalog():
                if old_catalog is None:
                    os.environ.pop('OCR_EVIDENCE_CATALOG', None)
                else:
                    os.environ['OCR_EVIDENCE_CATALOG'] = old_catalog
            self.addCleanup(restore_catalog)
            for item in pointers:
                Path(item['path']).unlink()
        selected_output = self.app.dispatch('output_review_status', identity)['data'] if gate == 'output-child' else None
        if selected_output:
            binding = selected_output.get('parent_binding')
            self.assertIsInstance(binding, dict, selected_output)
            self.assertEqual(binding['parent_attempt_id'], identity['attempt_id'])
            self.assertEqual(binding['correction_attempt_id'], before['attempt_id'])
            self.assertEqual(binding['cycle_id'], before['cycles'][0]['cycle_id'])
            self.assertEqual(binding['stage'], 'correction_output_review')
            self.assertEqual(binding['preparation_sha256'], hashlib.sha256((work / 'output-review-preparation.json').read_bytes()).hexdigest())
        committed_iteration = json.loads((work / 'output-manifest.json').read_text())['iteration_id']
        export_intent = work / 'application/corrections' / before['cycles'][0]['cycle_id'] / 'export-intent.json'
        expected_iteration = json.loads(export_intent.read_text())['iteration_id'] if gate in (
            'prepare-correction-export', 'render-correction-export') else None
        rendering_path = export_intent.with_name('export-rendered.json')
        rendering = json.loads(rendering_path.read_text()) if gate == 'render-correction-export' else None
        self.app.close()
        self.app = Application(self.root, process_command=[sys.executable, '-B', str(native)],
            codex_runtime=self.runtime, context_runtime=self.context)
        checked = self.app.dispatch('reconcile_autonomous', identity)
        self.assertTrue(checked['ok'], checked)
        self.assertTrue(checked['data']['checkpoint']['valid'], checked)
        resumed = self.app.dispatch('resume_autonomous', {**identity,
            'reconciliation_id': checked['data']['reconciliation_id']})
        self.assertTrue(resumed['ok'], resumed)
        complete = self.wait(identity['run_id'])
        self.assertEqual(complete['state'], 'completed', complete)
        self.assertEqual(complete['attempt_id'], identity['attempt_id'])
        after = self.app.dispatch('correction_status', identity)['data']
        self.assertEqual(after['cycles_used'], 1, after)
        self.assertEqual(after['attempt_id'], before['attempt_id'])
        self.assertEqual(after['cycles'][0]['cycle_id'], before['cycles'][0]['cycle_id'])
        turns = json.loads(original.read_text())['turns']
        self.assertEqual(turns[:len(original_turns)], original_turns)
        if gate == 'export':
            self.assertEqual(json.loads((work / 'output-manifest.json').read_text())['iteration_id'], committed_iteration)
        if expected_iteration:
            self.assertEqual(json.loads((work / 'output-manifest.json').read_text())['iteration_id'], expected_iteration)
        if rendering:
            final = json.loads((work / 'output-manifest.json').read_text())
            self.assertEqual(final['pdf_sha256'], rendering['pdf_sha256'])
            self.assertEqual(final['txt_sha256'], rendering['txt_sha256'])
        if selected_output:
            final_output = self.app.dispatch('output_review_status', identity)['data']
            self.assertEqual(final_output['attempt_id'], selected_output['attempt_id'])
            self.assertEqual(len(list((work / 'application/output-review-attempts').glob('*/attempt.json'))), 2)
        for relative, expected in archived.items():
            self.assertEqual(hashlib.sha256((work / relative).read_bytes()).hexdigest(), expected, relative)
        self.assertEqual(self.app.dispatch('select_run', identity)['data']['project']['acceptance'], 'not_recorded')
