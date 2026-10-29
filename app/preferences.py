"""Durable global defaults and independent preferences for each source PDF."""
import copy
import fcntl
import hashlib
import json
from pathlib import Path

from .jobs import JobError, atomic_json
from tools.ocr_profiles import load_profile, validate_activity_overrides

DEFAULTS = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high'}
EFFORTS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra')


def validate(value):
    if not isinstance(value, dict) or set(value) not in ({'model', 'reasoning_effort'}, {'model', 'reasoning_effort', 'overrides'}):
        raise JobError('preferences_invalid', 'Předvolby musí obsahovat model a reasoning.')
    model = value['model']
    if (not isinstance(model, str) or not model.strip() or model != model.strip() or
            len(model) > 200 or any(ord(c) < 32 for c in model)):
        raise JobError('preferences_invalid', 'Model musí mít neprázdný název bez řídicích znaků.')
    if value['reasoning_effort'] not in EFFORTS:
        raise JobError('preferences_invalid', 'Nepodporovaná úroveň reasoningu.')
    try:
        validate_activity_overrides(value.get('overrides', {}))
    except ValueError as error:
        raise JobError('preferences_invalid', str(error)) from None
    result = copy.deepcopy(value)
    if not result.get('overrides'):
        result.pop('overrides', None)
    return result


class Preferences:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / 'application/preferences.json'

    def read(self):
        if not self.path.exists():
            return {'schema_version': 1, 'global': dict(DEFAULTS), 'editions': {}}
        try:
            value = json.loads(self.path.read_text())
            if value['schema_version'] != 1 or not isinstance(value['editions'], dict):
                raise ValueError('Invalid preference store')
            validate(value['global'])
            for key, item in value['editions'].items():
                if len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
                    raise ValueError('Invalid edition identity')
                validate(item)
            return value
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise JobError('preferences_invalid', f'Uložené předvolby nelze načíst: {error}') from None

    def update(self, mutate):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with (self.path.parent / 'preferences.lock').open('a') as stream:
                fcntl.flock(stream, fcntl.LOCK_EX)
                value = self.read()
                mutate(value)
                atomic_json(self.path, value)
            return value
        except OSError as error:
            raise JobError('preferences_unwritable', f'Předvolby nelze uložit: {error}') from None

    def global_value(self):
        return copy.deepcopy(self.read()['global'])

    def project_value(self, edition_id):
        # A legacy project has independent original defaults, not live inheritance.
        return copy.deepcopy(self.read()['editions'].get(edition_id, DEFAULTS))

    def capture_imported(self, editions, previous):
        missing = [item['edition_id'] for item in editions if item['edition_id'] not in self.read()['editions']]
        if missing:
            def capture(value):
                for identifier in missing:
                    value['editions'].setdefault(identifier, copy.deepcopy(DEFAULTS if identifier in previous else value['global']))
            self.update(capture)

    def set_global(self, preferences):
        preferences = validate(preferences)
        self.update(lambda value: value.update({'global': preferences}))
        return preferences

    def set_project(self, edition_id, preferences):
        preferences = validate(preferences)
        self.update(lambda value: value['editions'].update({edition_id: preferences}))
        return preferences

    def resolve_profile(self, profile, edition_id):
        effective = copy.deepcopy(profile['profile'])
        preferences = self.project_value(edition_id)
        effective['parameters'].update({key: preferences[key] for key in ('model', 'reasoning_effort')})
        if preferences.get('overrides'):
            effective['parameters']['activity_overrides'] = preferences['overrides']
        else:
            effective['parameters'].pop('activity_overrides', None)
        if effective == profile['profile']:
            return profile
        # The external profile remains untouched; this exact evaluated copy is
        # handed to the unchanged native import protocol and then frozen there.
        raw = (json.dumps(effective, ensure_ascii=False) + '\n').encode()
        digest = hashlib.sha256(raw).hexdigest()
        path = self.root / 'application/evaluated-profiles' / (digest + '.json')
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                atomic_json(path, effective)
            return load_profile(path, expected_sha256=digest)
        except OSError as error:
            raise JobError('preferences_unwritable', f'Vyhodnocený profil nelze uložit: {error}') from None
