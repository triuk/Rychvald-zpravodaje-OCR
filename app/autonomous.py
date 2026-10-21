"""One owned asynchronous action over the existing public stage contracts."""
import copy
import json
from pathlib import Path
import os
import threading
import time
import uuid
import fcntl

from .codex import now, process_identity
from .jobs import JobError, atomic_json, sha
from .recovery import inspect_original, unchanged_originals, local_recovery_routes, recover_local, verify_completed_reuse


class AutonomousJobs:
    def __init__(self, application):
        self.app = application
        self.active = None

    def _lease(self):
        self.app.root.mkdir(parents=True, exist_ok=True)
        stream = (self.app.root / '.application-execution.lock').open('a+')
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            stream.close()
            raise JobError('operation_active', 'Another application owns this registry.') from None
        return stream

    def _bindings(self, run, payload):
        import hashlib
        source = self.app.root / run['artifacts']['source']['path']
        if sha(source) != run['project']['source_sha256']:
            raise JobError('source_corrupt', 'Registered source bytes changed.')
        resources = {}
        for runtime in (self.app.codex.runtime, self.app.context.context_runtime):
            for item in runtime.get('files', []):
                if sha(Path(item['path'])) != item['sha256']:
                    raise JobError('runtime_changed', 'Pinned AI runtime changed.')
                resources[item['path']] = item['sha256']
        environment = payload.get('environment') or os.environ.get('OCR_ENVIRONMENT')
        if environment:
            resources[str(Path(environment).resolve())] = sha(Path(environment))
        return {'source_sha256': sha(source), 'profile_sha256': hashlib.sha256(
            json.dumps(run['run']['profile'], sort_keys=True).encode()).hexdigest(), 'resources': resources,
            'codex_runtime': self.app.codex.runtime, 'context_runtime': self.app.context.context_runtime}

    def busy(self):
        return self.active is not None

    def _managers(self):
        return tuple(manager for manager in (self.app.preparation, self.app.codex, self.app.context,
            self.app.reading, self.app.geometry, self.app.output_review, getattr(self.app, 'corrections', None)) if manager is not None)

    def start(self, run, payload, *, from_geometry=False, lease=None):
        if self.busy():
            raise JobError('operation_active', 'An autonomous action is already active.')
        lease = lease or self._lease()
        try:
            bindings = self._bindings(run, payload)
        except BaseException:
            lease.close()
            raise
        work = self.app.root / run['artifacts']['workspace']['path']
        identifier = uuid.uuid4().hex
        path = work / 'application/autonomous-attempts' / identifier / 'attempt.json'
        path.parent.mkdir(parents=True)
        value = {'schema_version': 1, 'attempt_id': identifier, 'run_id': run['project']['run_id'],
            'root': str(self.app.root), 'state': 'starting', 'stage': None, 'stages': [],
            'started_at': now(), 'ended_at': None, 'error': None, 'mode': 'from_geometry' if from_geometry else 'source_to_export',
            'owner_pid': os.getpid(), 'owner_start_ticks': process_identity(os.getpid()),
            'acceptance': 'not_recorded', 'validation': 'not_run', 'payload': copy.deepcopy(payload),
            'bindings': bindings, 'control': 'run', 'sessions': []}
        job = {'manifest': value, 'path': path, 'cancel': False, 'payload': copy.deepcopy(payload), 'lease': lease}
        atomic_json(path, value)
        self.active = job
        job['thread'] = threading.Thread(target=self._run, args=(job, from_geometry), daemon=True,
            name='OCR-autonomous-' + identifier)
        job['thread'].start()
        return copy.deepcopy(value)

    def _save(self, job):
        atomic_json(job['path'], job['manifest'])
        self.app.publish('autonomous_progress', run_id=job['manifest']['run_id'],
            attempt_id=job['manifest']['attempt_id'], state=job['manifest']['state'], stage=job['manifest']['stage'])

    def _wait(self, job, operation, flag=None):
        while True:
            response = self.app.dispatch(operation, {'run_id': job['manifest']['run_id']})
            if not response['ok']:
                raise JobError(**response['error'])
            value = response['data']
            entry = job['manifest']['stages'][-1]
            if value.get('attempt_id') != entry.get('attempt_id'):
                raise JobError('attempt_conflict', 'A different child attempt replaced the owned stage.')
            if value['state'] not in ('starting', 'running'):
                if job['cancel']:
                    raise JobError('operation_cancelled', 'Owned work stopped; original attempt remains available.')
                if value['state'] != 'completed' or flag and not value.get(flag):
                    error = value.get('error') or {'code': 'stage_incomplete', 'message': operation + ' did not verify its milestone.'}
                    raise JobError(error['code'], error['message'])
                return value
            time.sleep(.05)

    def _stage(self, job, name, action):
        prior = next((row for row in reversed(job['manifest']['stages']) if row['stage'] == name and row['state'] == 'completed'), None)
        if prior is not None:
            return prior.get('result', {})
        if job['cancel']:
            raise JobError('operation_cancelled', 'Autonomous action was stopped.')
        if job['manifest'].get('control') == 'pause':
            raise JobError('autonomous_paused', 'Paused after the current verified unit.')
        value = job['manifest']
        value['stage'] = name
        entry = {'stage': name, 'state': 'running', 'started_at': now(), 'ended_at': None, 'intent_id': uuid.uuid4().hex}
        value['stages'].append(entry)
        self._save(job)
        result = action()
        entry.update(state='completed', ended_at=now())
        entry['result'] = result
        entry['evidence'] = {}
        for key, relative in result.get('artifacts', {}).items():
            if key not in ('protocol', 'request', 'proposal', 'attempt', 'source_samples', 'sample_origin') or not isinstance(relative, str):
                continue
            path = (self.app.root / relative).resolve()
            if not path.is_relative_to(self.app.root) or not path.is_file():
                raise JobError('checkpoint_invalid', 'Completed stage evidence is missing or outside the registry.')
            entry['evidence'][str(path.relative_to(self.app.root))] = sha(path)
        if result.get('attempt_id'):
            entry['attempt_id'] = result['attempt_id']
        self._save(job)
        return result

    def _run(self, job, from_geometry):
        value = job['manifest']
        payload = {**job['payload'], 'run_id': value['run_id']}

        def stage(start, status, flag=None):
            with self.app._lock:
                if self.app._closing or job['cancel']:
                    raise JobError('operation_cancelled', 'Application is closing.')
                if value.get('control') == 'pause':
                    raise JobError('autonomous_paused', 'Paused before child allocation.')
                name = value['stages'][-1]['stage']
                previous = next((row for row in reversed(value['stages'][:-1]) if row['stage'] == name and row.get('attempt_id')), None)
                child_payload = dict(payload)
                if previous:
                    response = self.app.dispatch(status, {'run_id': value['run_id']})
                    if response['ok'] and response['data'].get('attempt_id') == previous['attempt_id'] and response['data']['state'] == 'completed':
                        value['stages'][-1].update(attempt_id=previous['attempt_id'], child_status_operation=status,
                            reused_from=previous['intent_id'])
                        self._save(job)
                        return response['data']
                    child_payload['previous_attempt_id'] = previous['attempt_id']
                    if name == 'prepare':
                        child_payload['resume_preparation'] = True
                    if name == 'reading':
                        child_payload['previous_reading_attempt_id'] = previous['attempt_id']
                    if name == 'context_diagnostic':
                        child_payload['previous_context_attempt_id'] = previous['attempt_id']
                binding = {'parent_attempt_id': value['attempt_id'], 'intent_id': value['stages'][-1]['intent_id'], 'stage': name}
                managers = self._managers()
                for manager in managers:
                    manager.launch_parent = binding
                try:
                    child = start(child_payload)
                finally:
                    for manager in managers:
                        manager.launch_parent = None
                if name == 'corrections' and child['state'] == 'completed' and not child.get('attempt_id'):
                    return child  # Native reservation can truthfully stop without an AI child.
                value['stages'][-1].update(attempt_id=child['attempt_id'], child_status_operation=status)
                self._save(job)
            return self._wait(job, status, flag)

        try:
            value['state'] = 'running'
            if not from_geometry:
                self._stage(job, 'prepare', lambda: stage(self.app.start_preparation, 'preparation_status', 'checkpoint_valid'))
                self._stage(job, 'model_diagnostic', lambda: stage(self.app.start_model_diagnostic,
                    'model_diagnostic_status', 'combination_verified'))
                self._stage(job, 'context_diagnostic', lambda: stage(self.app.start_context_diagnostic,
                    'context_status', 'autonomous_ocr_ready'))
                self._stage(job, 'reading', lambda: stage(self.app.start_reading, 'reading_status', 'reading_complete'))
                self._stage(job, 'geometry', lambda: stage(self.app.start_geometry, 'geometry_status', 'geometry_complete'))
            root, run_id = Path(value['root']), value['run_id']
            run = self.app.select_run(run_id)
            work = root / run['artifacts']['workspace']['path']
            arguments = ['export', run_id, '--geometry-checkpoint', work / 'geometry-checkpoint.json']
            if payload.get('existing_export_sha256'):
                arguments = ['verify-output-preparation', run_id, '--sha256', payload['prepared_review_sha256'],
                    '--output-manifest-sha256', payload['existing_export_sha256']]
            elif payload.get('environment'):
                arguments += ['--environment', payload['environment']]
            self._stage(job, 'export', lambda: self.app.process.request(root, *arguments, timeout=180,
                cancelled=lambda: job['cancel'], owned=lambda process: self._native_started(job, process)))
            self._stage(job, 'output_review', lambda: stage(self.app.start_output_review,
                'output_review_status', 'output_review_complete'))
            arguments = ['validate', run_id]
            if payload.get('environment'):
                arguments += ['--environment', payload['environment']]
            result = self._stage(job, 'validate', lambda: self.app.process.request(root, *arguments,
                allowed_returncodes=(0, 1, 2), timeout=120, cancelled=lambda: job['cancel'],
                owned=lambda process: self._native_started(job, process)))
            value.update(state='completed', validation=result['project']['validation'],
                phase=result['project']['phase'], acceptance=result['project']['acceptance'])
            if not payload.get('defer_corrections') and result['project']['validation'] != 'failed':
                def correction_action():
                    saved = self.app.corrections.status(root, run_id, work)
                    if saved['state'] == 'not_started':
                        selected = json.loads((work / 'output-manifest.json').read_text())
                        return stage(lambda parameters: self.app.start_corrections({**parameters,
                            'expected_iteration_id': selected['iteration_id'],
                            'expected_validation_sha256': sha(work / 'checks/run-validation.json')}), 'correction_status')
                    if saved['state'] == 'completed' and all(cycle['state'] == 'settled' for cycle in saved['cycles']):
                        return saved
                    raise JobError('correction_reconciliation_required', 'Original correction cycle and descendants require explicit recovery before continuation.')
                value['state'] = 'running'
                corrected = self._stage(job, 'corrections', correction_action)
                result = self.app.select_run(run_id)
                value.update(state='completed', validation=corrected['validation'],
                    phase=result['project']['phase'], acceptance=corrected['acceptance'])
        except Exception as error:
            value.update(state='paused' if getattr(error, 'code', '') == 'autonomous_paused' else 'interrupted' if job['cancel'] else 'failed',
                error={'code': getattr(error, 'code', 'autonomous_failed'), 'message': str(error)})
            if value['stages'] and value['stages'][-1]['state'] == 'running':
                value['stages'][-1].update(state=value['state'], ended_at=now(), error=value['error'])
        finally:
            value['ended_at'] = now()
            self._save(job)
            with self.app._lock:
                self.active = None
                job['lease'].close()

    def status(self, root, run_id, work):
        paths = list((work / 'application/autonomous-attempts').glob('*/attempt.json'))
        if not paths:
            return {'run_id': run_id, 'state': 'not_started', 'stages': []}
        values = [json.loads(path.read_text()) for path in paths]
        value = max(values, key=lambda row: row['started_at'])
        if value['root'] != str(root) or value['run_id'] != run_id:
            raise JobError('autonomous_identity_invalid', 'Saved action belongs to another registry/run.')
        if value['state'] in ('starting', 'running') and process_identity(value['owner_pid']) != value['owner_start_ticks']:
            value.update(state='interrupted', error={'code': 'owner_stopped', 'message': 'The owning application stopped; no automatic replay.'})
        return value

    def _native_started(self, job, process):
        job['manifest']['stages'][-1]['process'] = {'pid': process.pid, 'process_group': process.pid,
            'process_start_ticks': process_identity(process.pid)}
        self._save(job)

    def control(self, run, attempt_id, action):
        work = self.app.root / run['artifacts']['workspace']['path']
        value = self.status(self.app.root, run['project']['run_id'], work)
        if value.get('attempt_id') != attempt_id:
            raise JobError('attempt_conflict', 'Control must identify the exact saved autonomous attempt.')
        job = self.active
        if job is None or job['manifest']['attempt_id'] != attempt_id:
            if value['state'] in ('paused', 'interrupted', 'completed', 'failed'):
                return value
            raise JobError('owner_stopped', 'Reconcile the saved work before continuing.')
        job['manifest']['control'] = action
        for manager in self._managers():
            manager.control(action)
        if action == 'interrupt':
            job['cancel'] = True
            job['manifest']['state'] = 'interrupting'
        self._save(job)
        return copy.deepcopy(job['manifest'])

    def reconcile(self, run, attempt_id):
        work = self.app.root / run['artifacts']['workspace']['path']
        value = self.status(self.app.root, run['project']['run_id'], work)
        if self.busy() or value.get('attempt_id') != attempt_id or value['state'] not in ('paused', 'interrupted', 'failed'):
            raise JobError('reconciliation_required', 'Choose an inactive paused/interrupted attempt.')
        current = self._bindings(run, value['payload'])
        if current != value['bindings']:
            raise JobError('checkpoint_identity_changed', 'Source, frozen profile or environment changed.')
        identifier = uuid.uuid4().hex
        path = work / 'application/autonomous-attempts' / attempt_id / 'attempt.json'
        result = {'reconciliation_id': identifier, 'attempt_id': attempt_id, 'run_id': value['run_id'],
            'original_sha256': sha(path), 'checkpoint': {'valid': True}, 'provider': {'state': 'not_submitted'},
            'created_at': now()}
        if any(row['stage'] == 'corrections' and row['state'] != 'completed' for row in value['stages']):
            result['provider'] = {'state': 'unknown', 'safe_to_continue': False, 'turns': [], 'originals': {},
                'continuation_error': {'code': 'correction_reconciliation_required',
                    'message': 'Original correction cycle and descendant turns require explicit recovery; no automatic replay.'}}
        else:
            result['provider'] = inspect_original(self.app, work, value, path.parent / ('inspection-' + identifier))
        result['stage_links'] = [{'intent_id': row.get('intent_id'), 'attempt_id': row['attempt_id']} for row in value['stages'] if row.get('attempt_id')]
        result['local_recovery'] = local_recovery_routes(work, value)
        try:
            self._verify_checkpoint(run, value)
        except Exception as error:
            result['checkpoint'] = {'valid': False, 'error': {'code': getattr(error, 'code', 'checkpoint_invalid'), 'message': str(error)}}
        atomic_json(path.parent / ('reconciliation-' + identifier + '.json'), result)
        atomic_json(path.parent / ('reconciliation-' + identifier + '-integrity.json'), {
            'sha256': sha(path.parent / ('reconciliation-' + identifier + '.json'))})
        return result

    def resume(self, run, payload):
        work = self.app.root / run['artifacts']['workspace']['path']
        value = self.status(self.app.root, run['project']['run_id'], work)
        if self.busy() or value.get('attempt_id') != payload.get('attempt_id'):
            raise JobError('attempt_conflict', 'Choose the exact inactive attempt to resume.')
        path = work / 'application/autonomous-attempts' / value['attempt_id'] / 'attempt.json'
        identifier = payload.get('reconciliation_id')
        if not isinstance(identifier, str) or len(identifier) != 32 or not all(c in '0123456789abcdef' for c in identifier):
            raise JobError('reconciliation_required', 'Reconcile the original work before resume.')
        proof_path = path.parent / ('reconciliation-' + identifier + '.json')
        integrity = json.loads((path.parent / ('reconciliation-' + identifier + '-integrity.json')).read_text())
        if sha(proof_path) != integrity['sha256']:
            raise JobError('checkpoint_invalid', 'Saved reconciliation evidence changed.')
        proof = json.loads(proof_path.read_text())
        if proof['provider'].get('continuation_error'):
            raise JobError(**proof['provider']['continuation_error'])
        if not proof['provider']['safe_to_continue'] or not unchanged_originals(self.app.root, proof['provider']):
            raise JobError('reconciliation_required', 'Original AI delivery/state remains unknown or inspected evidence changed.')
        for link in proof['stage_links']:
            for row in value['stages']:
                if row.get('intent_id') == link['intent_id']:
                    row['attempt_id'] = link['attempt_id']
        verify_completed_reuse(self.app, work, value, proof['provider'], proof['local_recovery'])
        if not proof['checkpoint']['valid']:
            raise JobError('checkpoint_invalid', 'OCR checkpoint failed independently of original thread recovery.')
        self._verify_checkpoint(run, value)
        if proof['original_sha256'] != sha(path) or self._bindings(run, value['payload']) != value['bindings']:
            raise JobError('checkpoint_identity_changed', 'Reconciled work changed before resume.')
        lease = self._lease()
        try:
            if proof['original_sha256'] != sha(path) or self._bindings(run, value['payload']) != value['bindings']:
                raise JobError('checkpoint_identity_changed', 'Saved work changed before ownership was acquired.')
            for route in proof['local_recovery']:
                recover_local(self.app, work, value['run_id'], route)
        except BaseException:
            lease.close()
            raise
        value['sessions'].append({'ended_at': value['ended_at'], 'state': value['state'], 'reconciliation_id': identifier})
        value.update(state='starting', control='run', ended_at=None, error=None,
            owner_pid=os.getpid(), owner_start_ticks=process_identity(os.getpid()))
        job = {'manifest': value, 'path': path, 'cancel': False, 'payload': value['payload'], 'lease': lease}
        self.active = job
        atomic_json(path, value)
        job['thread'] = threading.Thread(target=self._run, args=(job, value['mode'] == 'from_geometry'), daemon=True)
        job['thread'].start()
        return copy.deepcopy(value)

    def _verify_checkpoint(self, run, value):
        from .context_runtime import verify_resources
        verify_resources(self.app.context.context_runtime, self.app.codex.runtime)
        arguments = ['verify-resume', value['run_id']]
        if any(row['stage'] == 'export' and row['state'] == 'completed' for row in value['stages']):
            arguments.append('--output')
        if value['payload'].get('environment'):
            arguments += ['--environment', value['payload']['environment']]
        self.app.process.request(self.app.root, *arguments)
        for row in value['stages']:
            if row['state'] != 'completed':
                continue
            for relative, digest in row.get('evidence', {}).items():
                path = (self.app.root / relative).resolve()
                if not path.is_relative_to(self.app.root) or not path.is_file() or sha(path) != digest:
                    raise JobError('checkpoint_invalid', 'Completed stage evidence changed: ' + relative)
            operation = row.get('child_status_operation')
            if operation:
                response = self.app.dispatch(operation, {'run_id': value['run_id']})
                if not response['ok']:
                    raise JobError(**response['error'])
                status = response['data']
                if status.get('attempt_id') != row['attempt_id'] or status['state'] != 'completed':
                    raise JobError('checkpoint_invalid', 'Completed child checkpoint failed validation: ' + row['stage'])
            if row['stage'] == 'export':
                # PDF/TXT/source hashes were checked by verify-resume --output.
                self.app.process.request(self.app.root, 'verify-geometry', value['run_id'])

    def close(self):
        if self.active:
            self.active['cancel'] = True
            self.active['manifest'].update(control='interrupt', state='interrupting')
            self._save(self.active)

    def join(self):
        job = self.active
        if job and job['thread'] is not threading.current_thread():
            job['thread'].join(timeout=5)
