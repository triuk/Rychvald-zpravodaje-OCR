"""Owned native preparation processes with durable attempts and queryable progress."""

from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
import uuid


class JobError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def atomic_json(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_history(path):
    with Path(path).open(encoding='utf-8') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
        text = stream.read()
    events = []
    for line in text.splitlines(keepends=True):
        if not line.endswith('\n'):
            break  # A terminated writer can leave its final event unpublished.
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError('History event must be an object.')
        events.append(value)
    return events


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def verify_checkpoint(work, expected, events):
    checkpoint = work / 'preparation-checkpoint.json'
    value = json.loads(checkpoint.read_text(encoding='utf-8'))
    identity = value['identity']
    if (value['status'] != 'completed' or identity['source_sha256'] != expected['source_sha256'] or
            identity['dpi'] != expected['dpi'] or identity['language'] != expected['language']):
        raise ValueError('Preparation checkpoint has a different identity or is not complete.')
    if sha(Path(expected['source_path'])) != expected['source_sha256']:
        raise ValueError('Registered source changed during preparation.')
    completed = next((event for event in reversed(events) if event['type'] == 'checkpoint_completed'), None)
    environment = next((event for event in events if event['type'] == 'step_completed' and event['step_id'] == 'environment'), None)
    if (completed is None or completed['checkpoint_sha256'] != sha(checkpoint) or environment is None or
            environment['environment'] != identity['environment']):
        raise ValueError('Checkpoint is not tied to this verified native attempt.')
    pages = value['counts']['pages']
    if type(pages) is not int or pages < 1:
        raise ValueError('Preparation page count is invalid.')
    required = {'input-manifest.json', 'ocr-commands.json', 'fresh-lines.json', 'preparation-identity.json'}
    for page in range(1, pages + 1):
        required.update({f'raster/page-{page}.png', f'raster/overview-{page}.png', f'raster/page-{page}-checkpoint.json'})
        for psm in (3, 11):
            required.update(f'ocr/page-{page}-psm{psm}{suffix}' for suffix in ('.hocr', '.tsv', '.txt', '.box', '-cache.json'))
    outputs = value['outputs']
    if not required.issubset(outputs):
        raise ValueError('Preparation checkpoint does not cover every required artifact.')
    for relative, digest in outputs.items():
        path = (work / relative).resolve()
        if not path.is_relative_to(work.resolve()) or not path.is_file() or sha(path) != digest:
            raise ValueError(f'Preparation artifact failed hash verification: {relative}')
    return value


class PreparationJobs:
    def __init__(self, command, publish):
        self.command = list(command)
        self.publish = publish
        self._lock = threading.RLock()
        self._active = None

    def busy(self):
        with self._lock:
            return self._active is not None

    def start(self, root, run, environment=None):
        with self._lock:
            if self._active is not None:
                raise JobError('operation_active', 'A local preparation is active; wait for it to finish.')
            run_id = run['project']['run_id']
            work = root / run['artifacts']['workspace']['path']
            history = root / run['artifacts']['history']['path']
            directory = work / 'application' / 'attempts'
            directory.mkdir(parents=True, exist_ok=True)
            attempt_id = uuid.uuid4().hex
            parameters = run['run']['profile']['parameters']
            command = [*self.command, '--root', str(root), '--json', 'prepare', run_id,
                       '--dpi', str(parameters['dpi']), '--language', parameters['language'],
                       '--progress-events', str(history), '--attempt-id', attempt_id]
            if environment is not None:
                command.extend(['--environment', environment])
            manifest_path = directory / f'{attempt_id}.json'
            manifest = {'schema_version': 1, 'attempt_id': attempt_id, 'run_id': run_id,
                        'root': str(root), 'operation': 'prepare', 'state': 'starting',
                        'started_at': datetime.now(timezone.utc).isoformat(), 'ended_at': None,
                        'pid': None, 'process_group': None, 'command': command,
                        'expected': {'source_sha256': run['project']['source_sha256'],
                                     'source_path': str(root / run['artifacts']['source']['path']),
                                     'dpi': parameters['dpi'], 'language': parameters['language']},
                        'environment': environment,
                        'history': str(history.relative_to(root)),
                        'stdout': str((directory / f'{attempt_id}.stdout.json').relative_to(root)),
                        'stderr': str((directory / f'{attempt_id}.stderr.log').relative_to(root)), 'error': None}
            atomic_json(manifest_path, manifest)
            job = {'manifest': manifest, 'path': manifest_path, 'work': work, 'cancel': False, 'process': None}
            self._active = job
            thread = threading.Thread(target=self._run, args=(job,), name=f'OCR-prepare-{attempt_id}', daemon=True)
            job['thread'] = thread
            thread.start()
            return self.status(root, run_id, work)

    def _run(self, job):
        value = job['manifest']
        root = Path(value['root'])  # Never use the GUI's mutable selected registry.
        seen = set()

        def forward():
            events = read_history(root / value['history'])
            for event in events:
                identifier = event.get('event_id')
                if event.get('attempt_id') == value['attempt_id'] and identifier not in seen:
                    seen.add(identifier)
                    self.publish('preparation_progress', root=str(root), run_id=value['run_id'], event=event)
            return [event for event in events if event.get('attempt_id') == value['attempt_id']]

        try:
            with (root / value['stdout']).open('wb') as stdout, (root / value['stderr']).open('wb') as stderr:
                process = subprocess.Popen(value['command'], stdout=stdout, stderr=stderr, start_new_session=True)
                with self._lock:
                    job['process'] = process
                    value.update(state='running', pid=process.pid, process_group=process.pid)
                    atomic_json(job['path'], value)
                while process.poll() is None:
                    if job['cancel']:
                        os.killpg(process.pid, signal.SIGTERM)
                    forward()
                    time.sleep(.05)
                value['returncode'] = process.returncode
            events = forward()
            if process.returncode < 0:
                raise JobError('process_terminated', f'Native preparation was terminated by signal {-process.returncode}.')
            raw = (root / value['stdout']).read_bytes()
            if len(raw) > 4096:
                raise JobError('ocr_protocol_invalid', 'Native summary exceeds 4 KiB.')
            response = json.loads(raw)
            if not isinstance(response, dict) or response.get('protocol_version') != 1 or response.get('operation') != 'prepare':
                raise JobError('ocr_protocol_invalid', 'Native process returned an invalid preparation response.')
            if response.get('error'):
                raise JobError(response['error']['code'], response['error']['message'])
            if process.returncode or response.get('status') != 'completed':
                raise JobError('prepare_failed', 'Native preparation did not complete successfully.')
            verify_checkpoint(job['work'], value['expected'], events)
            value['state'] = 'completed'
        except BaseException as error:
            value['state'] = 'interrupted' if job['cancel'] else 'failed'
            value['error'] = {'code': getattr(error, 'code', 'prepare_failed'), 'message': str(error)}
            try:
                events = read_history(root / value['history'])
                if not any(event.get('attempt_id') == value['attempt_id'] and
                           event.get('type') in ('attempt_failed', 'attempt_interrupted') for event in events):
                    event = {'schema_version': 1, 'event_id': value['attempt_id'] + ':worker-terminal',
                             'attempt_id': value['attempt_id'], 'run_id': value['run_id'],
                             'type': 'attempt_interrupted' if job['cancel'] else 'attempt_failed',
                             'step_id': 'preparation', 'timestamp': datetime.now(timezone.utc).isoformat(),
                             'elapsed_seconds': max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(value['started_at'])).total_seconds()),
                             'error': value['error']}
                    with (root / value['history']).open('a', encoding='utf-8') as stream:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                        stream.write(json.dumps(event, ensure_ascii=False) + '\n')
                        stream.flush()
                        os.fsync(stream.fileno())
                    self.publish('preparation_progress', root=str(root), run_id=value['run_id'], event=event)
            except (OSError, ValueError):
                pass  # The attempt manifest still preserves the original failure.
        finally:
            process = job['process']
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                except ProcessLookupError:
                    process.wait()
            value['ended_at'] = datetime.now(timezone.utc).isoformat()
            with self._lock:
                atomic_json(job['path'], value)
                self._active = None
            self.publish('preparation_finished', root=str(root), run_id=value['run_id'],
                         attempt_id=value['attempt_id'], state=value['state'], error=value['error'])

    def status(self, root, run_id, work):
        try:
            return self._status(root, run_id, work)
        except JobError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise JobError('attempt_invalid', f'Cannot read saved preparation evidence: {error}') from None

    def _status(self, root, run_id, work):
        paths = list((work / 'application' / 'attempts').glob('*.json'))
        paths = [path for path in paths if not path.name.endswith('.stdout.json')]
        if not paths:
            return {'run_id': run_id, 'state': 'not_started', 'events': [], 'counts': {}, 'checkpoint_valid': False}
        values = [json.loads(path.read_text(encoding='utf-8')) for path in paths]
        value = max(values, key=lambda item: item['started_at'])
        if value['root'] != str(root) or value['run_id'] != run_id:
            raise JobError('attempt_invalid', 'Saved preparation attempt has a different identity.')
        events = [event for event in read_history(root / value['history']) if event.get('attempt_id') == value['attempt_id']]
        units, active = {}, {}
        counts = {'pages_total': 0, 'pages_completed': 0, 'ocr_total': 0, 'ocr_completed': 0,
                  'rasters_cached': 0, 'ocr_cached': 0, 'totals_known': False}
        for event in events:
            kind, step = event['type'], event['step_id']
            if kind == 'units_planned':
                counts.update(pages_total=event['pages_total'], ocr_total=event['ocr_total'], totals_known=True)
            if kind in ('step_started', 'unit_started'):
                active[step] = event
            elif kind in ('step_completed', 'step_failed', 'unit_completed', 'unit_cached'):
                active.pop(step, None)
            elif kind in ('attempt_completed', 'attempt_failed', 'attempt_interrupted'):
                active.clear()
            if kind in ('unit_completed', 'unit_cached'):
                units[step] = event
        for event in units.values():
            raster = event['unit_kind'] == 'raster'
            counts['pages_completed' if raster else 'ocr_completed'] += 1
            if event['type'] == 'unit_cached':
                counts['rasters_cached' if raster else 'ocr_cached'] += 1
        checkpoint_valid = False
        if value['state'] == 'completed':
            try:
                verify_checkpoint(work, value['expected'], events)
                checkpoint_valid = True
            except (OSError, ValueError, KeyError, TypeError) as error:
                value.update(state='invalidated', error={'code': 'checkpoint_invalid', 'message': str(error)})
        elapsed = (datetime.fromisoformat(value['ended_at']) if value['ended_at'] else datetime.now(timezone.utc)) - datetime.fromisoformat(value['started_at'])
        return {**value, 'events': events[-200:], 'counts': counts, 'active_steps': list(active),
                'elapsed_seconds': max(0, elapsed.total_seconds()), 'checkpoint_valid': checkpoint_valid}

    def close(self):
        with self._lock:
            job = self._active
            if job is not None:
                job['cancel'] = True
        if job is not None:
            job['thread'].join(timeout=10)
            process = job['process']
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                job['thread'].join(timeout=3)
