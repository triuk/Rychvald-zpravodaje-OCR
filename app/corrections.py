"""Owned bounded correction worker; opening history never submits a provider request."""
import copy
import json
import os
from pathlib import Path
import threading
import time
import uuid

from .context import ContextJobs
from .codex import now, process_identity
from .jobs import JobError, atomic_json, sha
from .visual_session import examine
from .geometry_contract import GEOMETRY_PROMPT, GEOMETRY_SCHEMA
from .reading_contract import obj, array, LINE, UNIT, UNRESOLVED, PUBLISHER, RISK, STRING
from tools.ocr_correction_graph import output_binding, output_child


REPAIR_PROMPT = '''Read the attached targeted ORIGINAL source crops and bound findings. Use the frozen
profile repair instruction below. Return your actual native review patch, specific decisions and source
evidence. Preserve readable publisher errors, unrelated lines, independent sample expectations and
unresolved source uncertainty. Never change code, source, profile, runtime or acceptance. Do not repair
whitespace/geometry when the scan does not support a meaningful change. An empty patch honestly stops.
The native review patch uses lines:[{line:COMPLETE_REPLACEMENT_LINE}], optional units (complete ordered
unit list from all_units), and related unresolved/publisher_errors/risk_register lists INSIDE each line
edit. Source crop bbox gives ORIGINAL raster coordinates; translate crop pixels by that bbox origin.
Diagnostic overlays are auxiliary evidence. Keep all unrelated review data and unit positions unchanged.
Return expected_review_sha256, expected_iteration_id, target_finding_ids, images_examined (exact original
path/sha256 objects), patch, decisions:[{finding_id,reason,evidence:[attached image path]}], and
remaining_uncertainties. No invented image-reading claim or editorial correction.
CORRECTION_PACKET\n'''

REPAIR_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required':
    ['expected_review_sha256', 'expected_iteration_id', 'target_finding_ids', 'images_examined', 'patch',
     'decisions', 'remaining_uncertainties'], 'properties': {
        'expected_review_sha256': {'type': 'string'}, 'expected_iteration_id': {'type': 'string'},
        'target_finding_ids': {'type': 'array', 'items': {'type': 'string'}},
        'images_examined': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
            'required': ['path', 'sha256'], 'properties': {'path': {'type': 'string'}, 'sha256': {'type': 'string'}}}},
        'patch': {'anyOf': [obj(properties) for properties in (
            {'lines': array({'anyOf': [obj({'line': LINE}), obj({'line': LINE,
                'unresolved': array(UNRESOLVED), 'publisher_errors': array(PUBLISHER), 'risk_register': array(RISK)})]})},
            {'lines': array({'anyOf': [obj({'line': LINE}), obj({'line': LINE,
                'unresolved': array(UNRESOLVED), 'publisher_errors': array(PUBLISHER), 'risk_register': array(RISK)})]}),
                'units': array(UNIT)},
            {'lines': array({'anyOf': [obj({'line': LINE}), obj({'line': LINE,
                'unresolved': array(UNRESOLVED), 'publisher_errors': array(PUBLISHER), 'risk_register': array(RISK)})]}),
                'units': array(UNIT), 'drop_lines': array(STRING)})]},
        'decisions': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
            'required': ['finding_id', 'reason', 'evidence'], 'properties': {'finding_id': {'type': 'string'},
                'reason': {'type': 'string'}, 'evidence': {'type': 'array', 'items': {'type': 'string'}}}}},
        'remaining_uncertainties': {'type': 'array', 'items': {'type': 'string'}}}}


class CorrectionJobs(ContextJobs):
    namespace = 'correction-attempts'
    step_id = 'corrections'

    def __init__(self, application, runtime=None, context_runtime=None):
        super().__init__(application.publish, runtime, context_runtime)
        self.app = application
        self.process = application.process

    def start_corrections(self, root, run, payload):
        work = root / run['artifacts']['workspace']['path']
        self.process.request(root, 'reserve-correction', run['project']['run_id'],
            '--expected-iteration-id', payload['expected_iteration_id'],
            '--expected-validation-sha256', payload['expected_validation_sha256'])
        ledger = json.loads((work / 'application/corrections/ledger.json').read_text())
        if ledger['stop_reason']:
            return self.status(root, run['project']['run_id'], work)
        return super().start(root, run, operation='corrections', metadata={'payload': payload})

    def _event(self, job, kind, **details):
        super()._event(job, kind, **details)
        if job.get('cycle_id'):
            # Attempt identity and all native thread/turn/connection IDs are
            # durable before the next stage. The native budget stays reserved.
            atomic_json(job['directory'] / 'cycle-link.json', {'cycle_id': job['cycle_id'],
                'attempt_id': job['manifest']['attempt_id'], 'turns': job['manifest'].get('turns', []),
                'connections': job['manifest'].get('connections', [])})

    def _publication(self, proof, proposal):
        value = {'schema_version': 1, 'visual_turn': proof, 'runtime': self.runtime,
            'context_runtime': self.context_runtime,
            'evidence': {'protocol': proof['protocol'], 'proposal': {'path': str(proposal), 'sha256': sha(proposal)}}}
        for index, item in enumerate([*self.runtime['files'], *self.context_runtime.get('files', []),
                *self.context_runtime.get('interpreters', [])]):
            if 'sha256' in item:
                value['evidence']['runtime_' + str(index)] = {'path': item['path'], 'sha256': item['sha256']}
        return value

    def resume_original(self, root, run, identifier, payload, *, reconciliation):
        """Continue an independently reconciled child without allocating a cycle."""
        with self._lock:
            if self._active is not None:
                raise JobError('operation_active', 'An original correction is still owned.')
            work = root / run['artifacts']['workspace']['path']
            directory = work / 'application/correction-attempts' / identifier
            value = json.loads((directory / 'attempt.json').read_text())
            from .visual_continuation import original_reconciliation
            proof = original_reconciliation(root, work, value, reconciliation)
            ledger = work / 'application/corrections/ledger.json'
            self.process.request(root, 'verify-correction-resume', value['run_id'], '--attempt', identifier,
                '--ledger-sha256', sha(ledger))
            session = directory / 'recovery-sessions' / uuid.uuid4().hex
            session.mkdir(parents=True)
            atomic_json(session / 'original-attempt.json', value)
            original_protocol = session / 'original-protocol.jsonl'
            source_protocol = root / value['artifacts']['protocol']
            original_protocol.write_bytes(source_protocol.read_bytes() if source_protocol.exists() else b'')
            atomic_json(session / 'reconciliation-reference.json', reconciliation)
            value.setdefault('recovery_sessions', []).append({'path': str(session.relative_to(work)),
                'original_sha256': sha(session / 'original-attempt.json'), 'started_at': now()})
            value.update(state='starting', error=None, ended_at=None, owner_pid=os.getpid(),
                owner_start_ticks=process_identity(os.getpid()))
            atomic_json(directory / 'attempt.json', value)
            job = {'manifest': value, 'directory': directory, 'workspace': directory / 'workspace',
                'history': root / run['artifacts']['history']['path'], 'cancel': False, 'rpc': None,
                'metadata': {'payload': payload}, 'resume_original': True, 'recovery_directory': session,
                'reconciliation': reconciliation, 'reconciliation_provider': proof['provider'],
                'reconciliation_protocol': original_protocol}
            self._active = job
            job['thread'] = threading.Thread(target=self._execute, args=(job,), daemon=True)
            job['thread'].start()
            return copy.deepcopy(value)

    def _examine(self, job, stage, prompt, schema, work, images):
        directory = job['directory'] / stage
        if job.get('resume_original'):
            continuations = [row for row in job['manifest'].get('continuations', []) if row['stage'] == stage]
            previous = [row for row in job['manifest']['turns'] if row['stage'] == stage]
            if continuations:
                directory = job['root'] / continuations[-1]['directory']
            elif previous:
                directory = (job['root'] / previous[-1]['protocol']).parent
            if not directory.resolve().is_relative_to(job['directory']):
                raise JobError('attempt_conflict', 'Original visual phase escaped its correction attempt.')
        if job.get('resume_original') and directory.exists():
            protocol = directory / 'protocol.jsonl'
            frames = [json.loads(raw) for raw in protocol.read_text().splitlines()] if protocol.exists() else []
            if any(row['direction'] == 'client' and row['message'].get('method') == 'turn/start' for row in frames):
                from .visual_continuation import reserve_continuation
                continuation = reserve_continuation(self, job, stage, directory, frames, prompt, schema, images)
                if continuation is not None:
                    job['current_continuation'] = continuation
                    try:
                        return examine(self, job, stage, prompt, schema, work, images,
                            directory=job['root'] / continuation['directory'])
                    finally:
                        job.pop('current_continuation', None)
                from .visual_recovery import original_visual
                answer, proof = original_visual(directory, work, images, prompt, schema, job['directory'] / 'protocol.jsonl')
                records = [row for row in job['manifest']['turns'] if row['stage'] == stage and
                    row['thread_id'] == proof['thread_id'] and row['turn_id'] == proof['turn_id']]
                if len(records) != 1:
                    raise JobError('original_result_unavailable', 'Original completed visual turn binding is unavailable.')
                recovered = job['recovery_directory'] / stage
                recovered.mkdir()
                proposal = recovered / 'proposal.json'
                atomic_json(proposal, answer)
                records[0].update(state='completed', answer=json.dumps(answer, ensure_ascii=False),
                    proposal=str(proposal.relative_to(job['root'])), reused_original=proof)
                self._event(job, 'correction_original_visual_reused', stage=stage,
                    thread_id=proof['thread_id'], turn_id=proof['turn_id'])
                return answer, proof, proposal
            # Initialization stopped before submission. Keep its original files;
            # the first actual turn gets a separately recorded physical workspace.
            directory = job['recovery_directory'] / stage
        return examine(self, job, stage, prompt, schema, work, images, directory=directory)

    def _boundary(self, job):
        if job['cancel']:
            raise JobError('operation_cancelled', 'Correction stopped before the next phase.')
        if job.get('pause'):
            raise JobError('autonomous_paused', 'Correction paused before the next phase.')

    def _output_review(self, job, cycle, payload):
        value, root, work = job['manifest'], job['root'], job['directory'].parents[2]
        try:
            intent, original = output_child(work, value, cycle['cycle_id'])
        except ValueError as error:
            raise JobError('attempt_conflict', str(error)) from error
        environment = ['--environment', payload['environment']] if payload.get('environment') else []
        if intent is None:
            self.process.request(root, 'prepare-output-review', value['run_id'], *environment, timeout=120)
            self._boundary(job)
            intent = {'cycle_id': cycle['cycle_id'], 'cycle_index': cycle['index'], 'stage_intent_id': uuid.uuid4().hex,
                'preparation_sha256': sha(work / 'output-review-preparation.json'),
                'output_manifest_sha256': sha(work / 'output-manifest.json'),
                'iteration_id': json.loads((work / 'output-manifest.json').read_text())['iteration_id']}
            intent['binding'] = output_binding(value, intent)
            value.setdefault('output_intents', []).append(intent)
            self._event(job, 'correction_output_intent_saved', cycle_id=cycle['cycle_id'], stage_intent_id=intent['stage_intent_id'])
        if sha(work / 'output-manifest.json') != intent['output_manifest_sha256']:
            raise JobError('checkpoint_invalid', 'Original correction output iteration changed.')
        self._boundary(job)
        with self.app._lock:
            if original is None:
                self.app.output_review.launch_parent = intent['binding']
                try:
                    child = self.app.start_output_review({'run_id': value['run_id'], 'environment': payload.get('environment'),
                        'prepared_review_sha256': intent['preparation_sha256']})
                finally:
                    self.app.output_review.launch_parent = None
                intent['attempt_id'] = child['attempt_id']
            else:
                child = self.app.output_review.status(root, value['run_id'], work)
                if child.get('attempt_id') != original['attempt_id']:
                    raise JobError('attempt_conflict', 'A different output child replaced the reserved correction child.')
                if child['state'] != 'completed':
                    if not job.get('resume_original'):
                        raise JobError('reconciliation_required', 'Original output child requires explicit reconciliation.')
                    run = self.app.select_run(value['run_id'])
                    child = self.app.output_review.resume_original(root, run, original['attempt_id'],
                        intent['preparation_sha256'], payload.get('environment'), intent['binding'],
                        reconciliation=job['reconciliation'])
            intent['attempt_id'] = child['attempt_id']
            if not any(row['cycle_id'] == cycle['cycle_id'] and row['stage'] == 'output_review' for row in value.get('children', [])):
                value.setdefault('children', []).append({'cycle_id': cycle['cycle_id'], 'stage': 'output_review',
                    'attempt_id': child['attempt_id']})
            self._event(job, 'correction_output_review_started', cycle_id=cycle['cycle_id'], child_attempt_id=child['attempt_id'])
        while not job['cancel']:
            child = self.app.output_review.status(root, value['run_id'], work)
            if child.get('attempt_id') != intent.get('attempt_id', original['attempt_id'] if original else None):
                raise JobError('attempt_conflict', 'A different output child replaced the reserved correction child.')
            if child['state'] not in ('starting', 'running'):
                return child
            time.sleep(.05)
        raise JobError('operation_cancelled', 'Correction stopped during original output examination.')

    def _run(self, job):
        value = job['manifest']
        root = job['root'] = Path(value['root'])
        work = job['directory'].parents[2]
        payload = job['metadata']['payload']
        environment = ['--environment', payload['environment']] if payload.get('environment') else []
        started = time.monotonic()
        cycle_id = None
        value.update(state='running', context_runtime=copy.deepcopy(self.context_runtime))
        value.setdefault('turns', [])
        try:
            while not job['cancel']:
                ledger = json.loads((work / 'application/corrections/ledger.json').read_text())
                cycle = ledger['cycles'][-1]
                cycle_id = job['cycle_id'] = cycle['cycle_id']
                if cycle.get('attempt_id') != value['attempt_id']:
                    self.process.request(root, 'bind-correction', value['run_id'], '--cycle-id', cycle_id,
                        '--attempt', job['directory'] / 'attempt.json')
                packet = json.loads((work / cycle['plan']).read_text())
                value.update(cycle_id=cycle_id, cycle_index=cycle['index'])
                self._boundary(job)
                outcome = work / 'application/corrections' / cycle_id / 'outcome.json'
                if cycle['state'] == 'settled' or outcome.is_file():
                    self.process.request(root, 'verify-correction-resume', value['run_id'],
                        '--attempt', value['attempt_id'], '--ledger-sha256', sha(work / 'application/corrections/ledger.json'))
                    if cycle['state'] != 'settled':
                        self.process.request(root, 'adopt-correction-outcome', value['run_id'], '--cycle-id', cycle_id)
                    ledger = json.loads((work / 'application/corrections/ledger.json').read_text())
                    self._event(job, 'correction_outcome_adopted', cycle_id=cycle_id,
                        outcome_sha256=sha(outcome), stop_reason=ledger['stop_reason'])
                    if ledger['stop_reason']:
                        break
                    self._boundary(job)
                    saved = json.loads(outcome.read_text())
                    self.process.request(root, 'reserve-correction', value['run_id'],
                        '--expected-iteration-id', saved['iteration_id'], '--expected-validation-sha256', saved['validation_sha256'])
                    continue
                if cycle['state'] == 'reserved':
                    value['stage'] = 'targeted_repair'
                    if cycle.get('patch_intent') or (work / 'application/corrections' / cycle_id / 'patch-intent.json').exists():
                        self.process.request(root, 'adopt-correction-patch', value['run_id'], '--cycle-id', cycle_id)
                    else:
                        self._event(job, 'correction_started', cycle_id=cycle_id, cycle_index=cycle['index'])
                        answer, proof, proposal = self._examine(job, 'repair_' + str(cycle['index']),
                            REPAIR_PROMPT + json.dumps(packet, ensure_ascii=False), REPAIR_SCHEMA, work, packet['images'])
                        publication = job['directory'] / ('publication-' + cycle_id + '.json')
                        atomic_json(publication, self._publication(proof, proposal))
                        self.process.request(root, 'publish-correction', value['run_id'], '--cycle-id', cycle_id,
                            '--proposal', publication)
                value['stage'] = 'geometry'
                self._event(job, 'correction_patch_published', cycle_id=cycle_id)
                self._boundary(job)
                verified = self.process.request(root, 'verify-correction-resume', value['run_id'],
                    '--attempt', value['attempt_id'], '--ledger-sha256', sha(work / 'application/corrections/ledger.json'))['counts']
                previous = json.loads((work / 'application/corrections/ledger.json').read_text())['cycles'][-1]
                if not verified['correction_geometry_published']:
                    if not verified['correction_geometry_prepared']:
                        self.process.request(root, 'prepare-correction-geometry', value['run_id'], '--cycle-id', cycle_id,
                            *environment, timeout=120)
                    self._boundary(job)
                    prepared_path = work / 'geometry-preparation.json'
                    prepared = json.loads(prepared_path.read_text())
                    prepared['preparation_sha256'] = sha(prepared_path)
                    observations, proof, proposal = self._examine(job, 'geometry_' + str(cycle['index']),
                        GEOMETRY_PROMPT + json.dumps(prepared, ensure_ascii=False), GEOMETRY_SCHEMA, work, prepared['images'])
                    checkpoint = self._publication(proof, proposal)
                    old_checkpoint = json.loads((work / previous['previous_snapshot'] / 'geometry-checkpoint.json').read_text())
                    checkpoint.update(status='examined_with_remaining_approximations',
                        preparation_sha256=sha(prepared_path), identity=prepared['identity'],
                        historical_reading=old_checkpoint['historical_reading'],
                        source_samples_sha256=sha(work / 'geometry-source-samples.json'),
                        export_validation='not_run', acceptance='separate_user_decision')
                    checkpoint['correction_scope'] = prepared['correction_scope']
                    checkpoint['evidence']['sample_origin'] = {'path': str(work / 'geometry-sample-origin.json'),
                        'sha256': sha(work / 'geometry-sample-origin.json')}
                    checkpoint_path = job['directory'] / ('checkpoint-' + cycle_id + '.json')
                    atomic_json(checkpoint_path, checkpoint)
                    self.process.request(root, 'publish-geometry', value['run_id'], '--checkpoint', checkpoint_path)
                self._boundary(job)
                value['stage'] = 'export'
                if not verified['correction_export_committed']:
                    self.process.request(root, 'prepare-correction-export', value['run_id'], '--cycle-id', cycle_id)
                    self._boundary(job)
                    if not verified['correction_export_rendered']:
                        self.process.request(root, 'render-correction-export', value['run_id'], '--cycle-id', cycle_id,
                            *environment, timeout=180)
                    self._boundary(job)
                    self._event(job, 'correction_export_started', cycle_id=cycle_id)
                    self.process.request(root, 'export', value['run_id'], '--geometry-checkpoint', work / 'geometry-checkpoint.json',
                        '--previous-snapshot', work / previous['previous_snapshot'], *environment, timeout=180)
                self._boundary(job)
                value['stage'] = 'output_review'
                child = self._output_review(job, previous, payload)
                if job['cancel']:
                    raise JobError('operation_cancelled', 'Correction stopped during output examination.')
                if child['state'] != 'completed' or not child.get('output_review_complete'):
                    error = child.get('error') or {'code': 'correction_review_failed', 'message': 'Output review incomplete.'}
                    raise JobError(**error)
                value['stage'] = 'validate'
                self._event(job, 'correction_validation_started', cycle_id=cycle_id)
                self.process.request(root, 'validate', value['run_id'], *environment,
                    allowed_returncodes=(0, 1, 2), timeout=120)
                self.process.request(root, 'settle-correction', value['run_id'], '--cycle-id', cycle_id)
                ledger = json.loads((work / 'application/corrections/ledger.json').read_text())
                self._event(job, 'correction_settled', cycle_id=cycle_id, stop_reason=ledger['stop_reason'])
                if ledger['stop_reason']:
                    break
                manifest = json.loads((work / 'output-manifest.json').read_text())
                self.process.request(root, 'reserve-correction', value['run_id'],
                    '--expected-iteration-id', manifest['iteration_id'],
                    '--expected-validation-sha256', sha(work / 'checks/run-validation.json'))
            value.update(state='interrupted' if job['cancel'] else 'completed')
        except Exception as error:
            paused = getattr(error, 'code', None) == 'autonomous_paused'
            value.update(state='paused' if paused else 'interrupted' if job['cancel'] else 'failed',
                error={'code': getattr(error, 'code', 'correction_failed'), 'message': str(error)})
            if cycle_id and not job['cancel'] and not paused:
                try:
                    from .failures import run_failure
                    failure = run_failure(root, self.app.select_run(value['run_id'], notify=False), {
                        'attempt_id': (value.get('parent_binding') or {}).get('parent_attempt_id', value['attempt_id']),
                        'error': value['error'], 'stages': [{'stage': 'corrections', 'attempt_id': value['attempt_id']}]})
                    if failure['scope'] == 'global' or failure['delivery_state'] in ('unknown', 'accepted'):
                        value['settlement_pending'] = failure
                    else:
                        reason = ('no_valid_change' if getattr(error, 'code', None) == 'correction_no_valid_change' else
                            'invalid_patch' if value.get('stage') == 'targeted_repair' and getattr(error, 'code', None) == 'correction_invalid' else
                            'technical_failure')
                        self.process.request(root, 'settle-correction', value['run_id'], '--cycle-id', cycle_id, '--reason', reason)
                except Exception as settle_error:
                    value['settlement_error'] = str(settle_error)
        finally:
            if job.get('rpc'):
                job['rpc'].close()
            value.update(ended_at=now(), elapsed_seconds=time.monotonic()-started)
            self._event(job, 'corrections_finished', state=value['state'], error=value['error'])
            with self._lock:
                self._active = None

    def status(self, root, run_id, work, operation=None):
        try:
            return self._correction_status(root, run_id, work)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise JobError('correction_invalid', str(error)) from error

    def _correction_status(self, root, run_id, work):
        path = work / 'application/corrections/ledger.json'
        if not path.exists():
            return {'run_id': run_id, 'state': 'not_started', 'cycles': [], 'cycles_used': 0, 'cycles_remaining': 3}
        ledger = json.loads(path.read_text())
        if ledger['run_id'] != run_id:
            raise JobError('correction_invalid', 'Correction ledger belongs to another run.')
        result = {**ledger, 'cycles_used': len(ledger['cycles']), 'cycles_remaining': 3-len(ledger['cycles'])}
        run = self.app.select_run(run_id)
        result.update(validation=run['project']['validation'], acceptance=run['project']['acceptance'],
            iteration_id=run['project'].get('iteration_id'), state='completed')
        result['open_items'] = json.loads((work / 'checks/run-validation.json').read_text())['open_items']
        if ledger['cycles']:
            latest = ledger['cycles'][-1]
            if latest.get('attempt'):
                attempt = json.loads((work / latest['attempt']).read_text())
                state = attempt['state']
                if state in ('starting', 'running') and process_identity(attempt['owner_pid']) != attempt['owner_start_ticks']:
                    state = 'interrupted'
                result.update(state=state, stage=attempt.get('stage'), attempt_id=attempt['attempt_id'], error=attempt.get('error'))
            elif latest['state'] != 'settled':
                result['state'] = 'interrupted'
        with self._lock:
            if self._active and self._active['manifest']['run_id'] == run_id:
                attempt = self._active['manifest']
                # A terminal in-memory value is not settled until its final
                # native outcome and attempt record have both been persisted.
                result.update(state='running', stage=attempt.get('stage'),
                    attempt_id=attempt['attempt_id'], error=attempt.get('error'))
        return result
