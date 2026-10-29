"""Asynchronous discovery of the selected runtime's actual model catalog."""
import copy
import hashlib
import json
from pathlib import Path
import threading
import uuid

from .codex import RpcProcess, now, scrub
from .jobs import JobError, atomic_json, sha


class ModelCapabilities:
    def __init__(self, runtime, publish):
        self.runtime = copy.deepcopy(runtime)
        self.publish = publish
        self.active = None
        self.lock = threading.Lock()

    @property
    def identity(self):
        return hashlib.sha256(json.dumps(self.runtime, sort_keys=True).encode()).hexdigest()

    def status(self, root):
        path = Path(root) / 'application/model-capabilities.json'
        if not path.exists():
            return {'state': 'not_checked', 'models': [], 'error': None}
        try:
            value = json.loads(path.read_text())
            if value.get('runtime_sha256') != self.identity:
                return {'state': 'runtime_changed', 'models': [], 'error': None}
            if value['state'] in ('starting', 'running') and self.active is None:
                return {**value, 'state': 'interrupted', 'models': [],
                        'error': {'code': 'catalog_interrupted', 'message': 'Načtení nabídky bylo přerušeno; obnovte ji.'}}
            return value
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise JobError('model_catalog_invalid', f'Nabídku modelů nelze načíst: {error}') from None

    def start(self, root):
        with self.lock:
            if self.active is not None:
                raise JobError('operation_active', 'Nabídka modelů se již načítá.')
            directory = Path(root) / 'application/model-catalog' / uuid.uuid4().hex
            directory.mkdir(parents=True)
            value = {'state': 'starting', 'models': [], 'error': None,
                     'runtime_sha256': self.identity, 'checked_at': None,
                     'started_at': now(), 'protocol': str(directory / 'protocol.jsonl')}
            job = {'root': Path(root), 'directory': directory, 'value': value, 'cancel': False, 'rpc': None}
            atomic_json(job['root'] / 'application/model-capabilities.json', value)
            self.active = job
            job['thread'] = threading.Thread(target=self.run, args=(job,), name='OCR-model-catalog', daemon=True)
            job['thread'].start()
            return copy.deepcopy(value)

    def run(self, job):
        value = job['value']
        def trace(direction, message):
            with (job['directory'] / 'protocol.jsonl').open('a') as stream:
                stream.write(json.dumps({'timestamp': now(), 'direction': direction, 'message': scrub(message)}) + '\n')
        def notify(message):
            if 'id' in message:
                raise JobError('model_catalog_invalid', 'Čtení nabídky nesmí spouštět nástroje nebo schvalování.')
        try:
            for resource in self.runtime['files']:
                if sha(Path(resource['path'])) != resource['sha256']:
                    raise JobError('codex_runtime_invalid', 'Připnuté prostředky runtime se změnily.')
            with (job['directory'] / 'stderr.log').open('w') as stderr:
                rpc = RpcProcess(self.runtime['command'], job['directory'], stderr, trace, lambda: job['cancel'])
                job['rpc'] = rpc
                value['state'] = 'running'
                atomic_json(job['root'] / 'application/model-capabilities.json', value)
                rpc.request('initialize', {'clientInfo': {'name': 'rychvald-model-catalog', 'version': '1.0'},
                    'capabilities': {'experimentalApi': True}}, notify)
                rpc.send({'method': 'initialized'})
                cursor, cursors, models = None, set(), []
                while True:
                    result = rpc.request('model/list', {'cursor': cursor, 'limit': 100}, notify)
                    for item in result['data']:
                        if isinstance(item.get('model'), str):
                            models.append({'model': item['model'],
                                'display_name': item.get('displayName', item['model']),
                                'input_modalities': item.get('inputModalities', []),
                                'reasoning_efforts': [entry['reasoningEffort'] for entry in item.get('supportedReasoningEfforts', [])]})
                    cursor = result.get('nextCursor')
                    if cursor is None:
                        break
                    if cursor in cursors:
                        raise JobError('model_catalog_invalid', 'Nabídka modelů neopustila předchozí stránku.')
                    cursors.add(cursor)
                value.update(state='completed', models=models, checked_at=now())
        except Exception as error:
            value.update(state='interrupted' if job['cancel'] else 'failed', models=[],
                error={'code': getattr(error, 'code', 'model_catalog_invalid'), 'message': str(error)})
        finally:
            if job['rpc'] is not None:
                job['rpc'].close()
            atomic_json(job['root'] / 'application/model-capabilities.json', value)
            with self.lock:
                self.active = None
            self.publish('model_capabilities_changed', root=str(job['root']), state=value['state'])

    def availability(self, root, preferences):
        catalog = self.status(root)
        if catalog['state'] != 'completed':
            return {'state': 'not_verified', 'message': 'Dostupnost ověří runtime; uložená volba nebyla nahrazena.'}
        supported = any(item['model'] == preferences['model'] and 'image' in item['input_modalities'] and
            preferences['reasoning_effort'] in item['reasoning_efforts'] for item in catalog['models'])
        return {'state': 'available' if supported else 'unavailable',
                'message': 'Kombinace je v nabídce runtime.' if supported else 'Runtime tuto kombinaci modelu, reasoningu a obrazu nenabízí.'}

    def close(self):
        job = self.active
        if job is not None:
            job['cancel'] = True
            job['thread'].join(timeout=8)
