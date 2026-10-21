"""Owned bounded correction worker; opening history never submits a provider request."""
import copy
import json
from pathlib import Path
import time

from .context import ContextJobs
from .codex import now, process_identity
from .jobs import JobError, atomic_json, sha
from .visual_session import examine
from .geometry_contract import GEOMETRY_PROMPT, GEOMETRY_SCHEMA
from .reading_contract import obj, array, LINE, UNIT, UNRESOLVED, PUBLISHER, RISK, STRING


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

    def _run(self, job):
        value = job['manifest']
        root = job['root'] = Path(value['root'])
        work = job['directory'].parents[2]
        payload = job['metadata']['payload']
        environment = ['--environment', payload['environment']] if payload.get('environment') else []
        started = time.monotonic()
        cycle_id = None
        value.update(state='running', turns=[], context_runtime=copy.deepcopy(self.context_runtime))
        try:
            while not job['cancel']:
                ledger = json.loads((work / 'application/corrections/ledger.json').read_text())
                cycle = ledger['cycles'][-1]
                cycle_id = job['cycle_id'] = cycle['cycle_id']
                self.process.request(root, 'bind-correction', value['run_id'], '--cycle-id', cycle_id,
                    '--attempt', job['directory'] / 'attempt.json')
                packet = json.loads((work / cycle['plan']).read_text())
                value.update(stage='targeted_repair', cycle_id=cycle_id, cycle_index=cycle['index'])
                self._event(job, 'correction_started', cycle_id=cycle_id, cycle_index=cycle['index'])
                answer, proof, proposal = examine(self, job, 'repair_' + str(cycle['index']),
                    REPAIR_PROMPT + json.dumps(packet, ensure_ascii=False), REPAIR_SCHEMA, work, packet['images'])
                publication = job['directory'] / ('publication-' + cycle_id + '.json')
                atomic_json(publication, self._publication(proof, proposal))
                self.process.request(root, 'publish-correction', value['run_id'], '--cycle-id', cycle_id,
                    '--proposal', publication)
                value['stage'] = 'geometry'
                self._event(job, 'correction_patch_published', cycle_id=cycle_id)
                self.process.request(root, 'prepare-correction-geometry', value['run_id'], '--cycle-id', cycle_id,
                    *environment, timeout=120)
                prepared_path = work / 'geometry-preparation.json'
                prepared = json.loads(prepared_path.read_text())
                prepared['preparation_sha256'] = sha(prepared_path)
                observations, proof, proposal = examine(self, job, 'geometry_' + str(cycle['index']),
                    GEOMETRY_PROMPT + json.dumps(prepared, ensure_ascii=False), GEOMETRY_SCHEMA, work, prepared['images'])
                checkpoint = self._publication(proof, proposal)
                previous = json.loads((work / 'application/corrections/ledger.json').read_text())['cycles'][-1]
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
                if job['cancel']:
                    raise JobError('operation_cancelled', 'Correction stopped before export.')
                value['stage'] = 'export'
                self._event(job, 'correction_export_started', cycle_id=cycle_id)
                self.process.request(root, 'export', value['run_id'], '--geometry-checkpoint', work / 'geometry-checkpoint.json',
                    '--previous-snapshot', work / previous['previous_snapshot'], *environment, timeout=180)
                value['stage'] = 'output_review'
                with self.app._lock:
                    child = self.app.start_output_review({'run_id': value['run_id'], 'environment': payload.get('environment')})
                    value.setdefault('children', []).append({'cycle_id': cycle_id, 'stage': 'output_review',
                        'attempt_id': child['attempt_id']})
                    self._event(job, 'correction_output_review_started', cycle_id=cycle_id, child_attempt_id=child['attempt_id'])
                while not job['cancel']:
                    child = self.app.output_review.status(root, value['run_id'], work)
                    if child['state'] not in ('starting', 'running'):
                        break
                    time.sleep(.05)
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
                reason = ('no_valid_change' if getattr(error, 'code', None) == 'correction_no_valid_change' else
                    'invalid_patch' if value.get('stage') == 'targeted_repair' and getattr(error, 'code', None) == 'correction_invalid' else
                    'technical_failure')
                try:
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
