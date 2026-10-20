"""One owned asynchronous action over the existing public stage contracts."""
import copy
import json
from pathlib import Path
import os
import threading
import time
import uuid

from .codex import now, process_identity
from .jobs import JobError, atomic_json


class AutonomousJobs:
    def __init__(self, application):
        self.app = application
        self.active = None

    def busy(self):
        return self.active is not None

    def start(self, run, payload, *, from_geometry=False):
        if self.busy():
            raise JobError('operation_active', 'An autonomous action is already active.')
        work = self.app.root / run['artifacts']['workspace']['path']
        identifier = uuid.uuid4().hex
        path = work / 'application/autonomous-attempts' / identifier / 'attempt.json'
        path.parent.mkdir(parents=True)
        value = {'schema_version': 1, 'attempt_id': identifier, 'run_id': run['project']['run_id'],
            'root': str(self.app.root), 'state': 'starting', 'stage': None, 'stages': [],
            'started_at': now(), 'ended_at': None, 'error': None, 'mode': 'from_geometry' if from_geometry else 'source_to_export',
            'owner_pid': os.getpid(), 'owner_start_ticks': process_identity(os.getpid()),
            'acceptance': 'not_recorded', 'validation': 'not_run'}
        job = {'manifest': value, 'path': path, 'cancel': False, 'payload': copy.deepcopy(payload)}
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
        while not job['cancel']:
            response = self.app.dispatch(operation, {'run_id': job['manifest']['run_id']})
            if not response['ok']:
                raise JobError(**response['error'])
            value = response['data']
            if value['state'] not in ('starting', 'running'):
                if value['state'] != 'completed' or flag and not value.get(flag):
                    error = value.get('error') or {'code': 'stage_incomplete', 'message': operation + ' did not verify its milestone.'}
                    raise JobError(error['code'], error['message'])
                return value
            time.sleep(.05)
        raise JobError('operation_cancelled', 'Autonomous action was stopped; original attempts remain available.')

    def _stage(self, job, name, action):
        if job['cancel']:
            raise JobError('operation_cancelled', 'Autonomous action was stopped.')
        value = job['manifest']
        value['stage'] = name
        entry = {'stage': name, 'state': 'running', 'started_at': now(), 'ended_at': None}
        value['stages'].append(entry)
        self._save(job)
        result = action()
        entry.update(state='completed', ended_at=now())
        if result.get('attempt_id'):
            entry['attempt_id'] = result['attempt_id']
        self._save(job)
        return result

    def _run(self, job, from_geometry):
        value = job['manifest']
        payload = {**job['payload'], 'run_id': value['run_id']}

        def stage(start, status, flag=None):
            with self.app._lock:
                child = start(payload)
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
            self._stage(job, 'export', lambda: self.app.process.request(root, *arguments, timeout=180))
            self._stage(job, 'output_review', lambda: stage(self.app.start_output_review,
                'output_review_status', 'output_review_complete'))
            arguments = ['validate', run_id]
            if payload.get('environment'):
                arguments += ['--environment', payload['environment']]
            result = self._stage(job, 'validate', lambda: self.app.process.request(root, *arguments,
                allowed_returncodes=(0, 1, 2), timeout=120))
            value.update(state='completed', validation=result['project']['validation'],
                phase=result['project']['phase'], acceptance=result['project']['acceptance'])
        except Exception as error:
            value.update(state='interrupted' if job['cancel'] else 'failed',
                error={'code': getattr(error, 'code', 'autonomous_failed'), 'message': str(error)})
            if value['stages'] and value['stages'][-1]['state'] == 'running':
                value['stages'][-1].update(state=value['state'], ended_at=now(), error=value['error'])
        finally:
            value['ended_at'] = now()
            self._save(job)
            with self.app._lock:
                self.active = None

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

    def close(self):
        if self.active:
            self.active['cancel'] = True

    def join(self):
        job = self.active
        if job and job['thread'] is not threading.current_thread():
            job['thread'].join(timeout=5)
