"""Durable operator queue; execution is delegated to the owned run manager."""
from contextlib import contextmanager
import copy
import fcntl
import json
import hashlib
import os
import threading
import time
import uuid

from .codex import now, process_identity
from .jobs import JobError, atomic_json
from .failures import run_failure, admission_failure


class RunQueue:
    def __init__(self, application):
        self.app = application
        self.worker = None
        self.token = uuid.uuid4().hex

    @contextmanager
    def locked(self):
        directory = self.app.root / 'application'
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / '.queue.lock').open('a+') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            path = directory / 'queue.json'
            if path.exists():
                try:
                    value = json.loads(path.read_text())
                    if value['schema_version'] != 1 or value['root'] != str(self.app.root):
                        raise ValueError('Queue belongs to another registry or schema.')
                except (ValueError, KeyError, TypeError) as error:
                    raise JobError('queue_invalid', str(error)) from None
            else:
                value = {'schema_version': 1, 'root': str(self.app.root), 'revision': 0,
                    'state': 'paused', 'reason': {'code': 'operator_paused', 'message': 'Waiting for explicit queue start.'},
                    'active_item_id': None, 'pending': [], 'items': [], 'history': []}
            yield value

    def save(self, value, action):
        value['revision'] += 1
        value['history'].append({'at': now(), 'action': action, 'state': value['state']})
        atomic_json(self.app.root / 'application/queue.json', value)
        self.app.publish('queue_changed', revision=value['revision'], state=value['state'])

    def status(self):
        with self.locked() as value:
            if value['state'] == 'running' and (value.get('owner_start_ticks') is None or
                    process_identity(value.get('owner_pid', -1)) != value.get('owner_start_ticks')):
                value.update(state='paused', reason={'code': 'owner_stopped', 'message': 'Application stopped; explicit recovery is required.'})
                self.save(value, 'owner_stopped')
            self._observe(value)
            result = copy.deepcopy(value)
            manual = self.app.root / 'application/manual-execution.json'
            result['manual_execution'] = json.loads(manual.read_text()) if manual.exists() else None
            return result

    def enqueue(self, payload):
        request_id = payload.get('request_id')
        if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 200:
            raise JobError('invalid_request', 'Enqueue requires a stable request_id (1..200 characters).')
        with self.locked() as value:
            fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            prior = next((i for i in value['items'] if i['request_id'] == request_id or
                payload.get('run_id') and i['run_id'] == payload['run_id']), None)
            if prior:
                if prior['request_id'] == request_id and prior['request_sha256'] != fingerprint:
                    raise JobError('queue_conflict', 'This request_id already identifies another enqueue intent.')
                if prior['run_id'] is None:
                    raise JobError('enqueue_recovery_required', 'Run creation response was not committed. Inspect existing named runs and enqueue the exact existing run; do not create it again.')
                return copy.deepcopy(prior)
            item = {'item_id': uuid.uuid4().hex, 'request_id': request_id, 'request_sha256': fingerprint,
                'edition_id': None, 'run_id': None, 'state': 'binding', 'parent_attempt_id': None,
                'options': {k: payload[k] for k in ('environment', 'reuse_from_run_id', 'defer_corrections') if k in payload},
                'enqueued_at': now(), 'started_at': None, 'ended_at': None, 'waiting_intervals': [],
                'reason': {'code': 'enqueue_recovery_required', 'message': 'Named run binding has not committed.'}}
            # Intent must precede the native publication: a lost ACK must never
            # cause another run creation, even if the application dies here.
            value['items'].append(item)
            self.save(value, 'enqueue_binding')
            if payload.get('run_id'):
                run = self.app.select_run(payload['run_id'])
            else:
                from pathlib import Path
                from .jobs import sha
                from tools.ocr_profiles import load_profile, run_name
                run_name(payload.get('name'))
                if not isinstance(payload.get('profile_sha256'), str) or len(payload['profile_sha256']) != 64:
                    raise JobError('invalid_request', 'Inspect the exact profile before enqueueing a new run.')
                load_profile(payload.get('profile_path'), expected_sha256=payload.get('profile_sha256'))
                source = payload.get('source_path')
                if not isinstance(source, str) or not Path(source).expanduser().is_file():
                    raise JobError('single_source_required', 'Choose one existing source PDF for a named queue run.')
                self.app.import_sources(source)
                edition_id = sha(Path(source).expanduser().resolve())
                run = self.app.create_run({**payload, 'edition_id': edition_id})
            if not run.get('run'):
                raise JobError('run_profile_required', 'Queue requires a named run with a frozen profile.')
            parent = self.app.autonomous.status(self.app.root, run['project']['run_id'],
                self.app.root / run['artifacts']['workspace']['path'])
            item.update(edition_id=run['edition_id'], run_id=run['project']['run_id'], state='pending',
                run_name=run['run']['name'], source_name=run['project']['original_name'],
                parent_attempt_id=parent.get('attempt_id'),
                waiting_intervals=[{'start': now(), 'end': None,
                    'reason': {'code': 'queued', 'message': 'Waiting for queue admission.'}}],
                reason={'code': 'queued', 'message': 'Waiting for queue admission.'})
            value['pending'].append(item['item_id'])
            self.save(value, 'enqueue')
            return copy.deepcopy(item)

    def reorder(self, payload):
        with self.locked() as value:
            if payload.get('expected_revision') != value['revision']:
                raise JobError('queue_conflict', 'Queue changed; refresh before reordering.')
            order = payload.get('item_ids')
            if not isinstance(order, list) or len(order) != len(value['pending']) or set(order) != set(value['pending']):
                raise JobError('invalid_request', 'Reorder must contain each pending item exactly once.')
            value['pending'] = order
            self.save(value, 'reorder')
            return copy.deepcopy(value)

    def resume(self, payload):
        with self.locked() as value:
            if value['state'] == 'running':
                raise JobError('operation_active', 'Queue already has an owner; no second scheduler may start.')
            if value['active_item_id']:
                item = next(i for i in value['items'] if i['item_id'] == value['active_item_id'])
                if payload.get('item_id') != item['item_id'] or payload.get('attempt_id') != item['parent_attempt_id'] or payload.get('run_id') != item['run_id']:
                    raise JobError('reconciliation_required', 'Reconcile the exact saved active queue item before continuing.')
                run = self.app.select_run(item['run_id'], notify=False)
                if item.get('launch_state') == 'not_started' and item.get('reason', {}).get('code') == 'runtime_changed':
                    prior = self.app.autonomous.status(self.app.root, item['run_id'],
                        self.app.root / run['artifacts']['workspace']['path'])
                    if prior['state'] != 'not_started':
                        raise JobError('reconciliation_required', 'A parent appeared after the rejected admission; inspect it before continuing.')
                    lease = self.app.autonomous._lease()
                    try:
                        self.app.autonomous.start(run, item['options'], lease=lease,
                            identifier=item['parent_attempt_id'], queue_item_id=item['item_id'])
                    except BaseException:
                        lease.close()
                        raise
                    item['launch_state'] = 'published'
                else:
                    self.app.autonomous.resume(run, payload)
                self._end_wait(item)
                item.update(state='running', reason=None, ended_at=None, observed_parent_state=None)
            value.update(state='running', reason=None, owner_pid=os.getpid(),
                owner_start_ticks=process_identity(os.getpid()), owner_token=self.token, owner_epoch=uuid.uuid4().hex)
            epoch = value['owner_epoch']
            self.save(value, 'resume')
        self.worker = threading.Thread(target=self._run, args=(epoch,), daemon=True, name='OCR-queue')
        self.worker.start()
        return self.status()

    @staticmethod
    def _end_wait(item):
        for interval in item.get('waiting_intervals', []):
            if interval['end'] is None:
                interval['end'] = now()

    def control(self, action):
        with self.locked() as value:
            reason = {'code': 'operator_paused' if action == 'pause' else 'operator_interrupted',
                'message': 'Queue paused after the current unit.' if action == 'pause' else 'Queue interrupted; original work requires reconciliation.'}
            value.update(state='paused', reason=reason, control=action)
            if value['active_item_id']:
                item = next(i for i in value['items'] if i['item_id'] == value['active_item_id'])
                if not any(i['end'] is None for i in item['waiting_intervals']):
                    item['waiting_intervals'].append({'start': now(), 'end': None, 'reason': reason})
                if self.app.autonomous.active and self.app.autonomous.active['manifest']['attempt_id'] == item['parent_attempt_id']:
                    self.app.autonomous.control(self.app.select_run(item['run_id'], notify=False), item['parent_attempt_id'], action)
            self.save(value, action)
            return copy.deepcopy(value)

    def close(self):
        if not (self.app.root / 'application/queue.json').exists():
            return
        with self.locked() as value:
            owned = value.get('owner_token') == self.token and (self.app.autonomous.busy() or value['state'] == 'running')
        if owned:
            self.control('interrupt')

    def owns_schedule(self):
        with self.locked() as value:
            return value['state'] == 'running' and value.get('owner_token') == self.token

    def _observe(self, value):
        if not value['active_item_id'] or self.app.autonomous.busy():
            return
        item = next(i for i in value['items'] if i['item_id'] == value['active_item_id'])
        if item.get('launch_state') == 'not_started':
            return  # Durable typed rejection preceded parent publication/worker creation.
        run = self.app.select_run(item['run_id'], notify=False)
        parent = self.app.autonomous.status(self.app.root, item['run_id'], self.app.root / run['artifacts']['workspace']['path'])
        if parent.get('attempt_id') != item['parent_attempt_id']:
            reason = {'code': 'attempt_conflict', 'message': 'Saved queue parent identity is unavailable; no replay.'}
            if value.get('reason') != reason:
                value.update(state='blocked', reason=reason)
                self.save(value, 'blocked')
            return
        if parent['state'] in ('starting', 'running', 'interrupting'):
            return
        if item.get('observed_parent_state') == parent['state']:
            return
        item['observed_parent_state'] = parent['state']
        item['ended_at'] = parent.get('ended_at')
        if parent['state'] == 'completed':
            item.update(state='awaiting_input' if parent['validation'] == 'ready_with_open_items' else
                'failed' if parent['validation'] == 'failed' else 'completed',
                reason={'code': parent['validation'], 'message': 'Run finished; validation and user acceptance remain separate.'})
            self._end_wait(item)
            value['active_item_id'] = None
        else:
            reason = run_failure(self.app.root, run, parent)
            reason['item_id'] = item['item_id']
            item.update(state=parent['state'], reason=reason)
            if value['state'] == 'paused' or parent['state'] in ('paused', 'interrupted') or reason['scope'] == 'global':
                if value['state'] != 'paused':
                    value.update(state='blocked', reason=reason)
                if not any(i['end'] is None for i in item['waiting_intervals']):
                    item['waiting_intervals'].append({'start': now(), 'end': None, 'reason': value['reason']})
            else:
                value['active_item_id'] = None
        self.save(value, 'item_observed')

    def _run(self, epoch):
        while True:
            with self.app._lock:
                with self.locked() as value:
                    if value.get('owner_epoch') != epoch:
                        return
                    if self.app._closing or value['state'] != 'running':
                        if self.app.autonomous.active and value.get('control'):
                            active = self.app.autonomous.active['manifest']
                            self.app.autonomous.control(self.app.select_run(active['run_id'], notify=False), active['attempt_id'], value['control'])
                        return
                    self._observe(value)
                    if value['state'] != 'running':
                        return
                    if not value['active_item_id'] and value['pending']:
                        item = next(i for i in value['items'] if i['item_id'] == value['pending'][0])
                        if item.get('parent_attempt_id'):
                            value['pending'].pop(0)
                            value.update(active_item_id=item['item_id'], state='blocked', reason={
                                'scope': 'global', 'category': 'reconciliation', 'code': 'reconciliation_required',
                                'message': 'This existing named run already has an attempt; reconcile that exact attempt before continuation.'})
                            self.save(value, 'saved_run_requires_reconciliation')
                            return
                        try:
                            lease = self.app.autonomous._lease()
                        except JobError as error:
                            if error.code != 'operation_active':
                                value.update(state='blocked', reason={'scope': 'global', 'category': 'reconciliation',
                                    'code': error.code, 'message': str(error)})
                                self.save(value, 'admission_blocked')
                                return
                        else:
                            item.update(state='starting', started_at=now(), parent_attempt_id=uuid.uuid4().hex, reason=None)
                            self._end_wait(item)
                            value['pending'].pop(0)
                            value['active_item_id'] = item['item_id']
                            self.save(value, 'item_starting')
                            run = None
                            try:
                                run = self.app.select_run(item['run_id'])
                                self.app.autonomous.start(run, item['options'], lease=lease,
                                    identifier=item['parent_attempt_id'], queue_item_id=item['item_id'])
                            except Exception as error:
                                lease.close()
                                path = (self.app.root / run['artifacts']['workspace']['path'] /
                                    'application/autonomous-attempts' / item['parent_attempt_id'] / 'attempt.json') if run is not None else None
                                proven = getattr(error, 'code', None) in ('runtime_changed', 'source_corrupt') and path is not None and not path.exists()
                                reason = admission_failure(error, item, proven_unstarted=proven)
                                item.update(state='failed', ended_at=now(), reason=reason,
                                    launch_state='not_started' if proven else 'unresolved')
                                if reason['scope'] == 'global':
                                    value.update(state='blocked', reason=reason)
                                    item['waiting_intervals'].append({'start': now(), 'end': None, 'reason': reason})
                                else:
                                    value['active_item_id'] = None
                                self.save(value, 'item_failed')
                    elif not value['active_item_id']:
                        value.update(state='paused', reason={'code': 'queue_empty', 'message': 'Queue finished.'})
                        self.save(value, 'empty')
                        return
            time.sleep(.05)
