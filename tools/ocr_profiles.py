"""Dependency-free version 1 external OCR profiles shared by app and process."""

import hashlib
import json
from pathlib import Path


MAX_PROFILE_BYTES = 1024 * 1024
AI_ACTIVITIES = ('reading', 'geometry', 'final_check', 'repair')


class ProfileError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def run_name(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 160 or
            value != value.strip() or any(ord(character) < 32 for character in value)):
        raise ProfileError('run_name_invalid', 'Run name must contain 1–160 visible characters without surrounding whitespace.')
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def load_profile(path, *, expected_sha256=None):
    if not isinstance(path, (str, Path)) or not str(path).strip():
        raise ProfileError('profile_missing', 'Choose an external JSON profile.')
    try:
        path = Path(path).expanduser().resolve()
        with path.open('rb') as stream:
            raw = stream.read(MAX_PROFILE_BYTES + 1)
    except (OSError, ValueError) as error:
        raise ProfileError('profile_unreadable', f'Cannot read profile: {error}') from None
    if len(raw) > MAX_PROFILE_BYTES:
        raise ProfileError('profile_invalid', 'Profile exceeds the 1 MiB limit.')
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ProfileError('profile_changed', 'Profile changed after inspection. Inspect the current version before creating a run.')
    try:
        text = raw.decode('utf-8')
        profile = json.loads(text, object_pairs_hook=_unique_object)
        if not isinstance(profile, dict) or set(profile) != {'schema_version', 'name', 'parameters', 'prompts'}:
            raise ValueError('Expected schema_version, name, parameters and prompts.')
        if type(profile['schema_version']) is not int or profile['schema_version'] != 1:
            raise ValueError('Only profile schema version 1 is supported.')
        run_name(profile['name'])
        parameters = profile['parameters']
        if not isinstance(parameters, dict) or set(parameters) not in ({'dpi', 'language', 'model', 'reasoning_effort'}, {'dpi', 'language', 'model', 'reasoning_effort', 'activity_overrides'}):
            raise ValueError('Parameters must specify dpi, language, model and reasoning_effort.')
        if type(parameters['dpi']) is not int or parameters['dpi'] < 1:
            raise ValueError('DPI must be a positive integer.')
        for key in ('language', 'model'):
            value = parameters[key]
            if not isinstance(value, str) or not value.strip() or value != value.strip() or any(ord(c) < 32 for c in value):
                raise ValueError(f'{key} must be a nonempty string without surrounding whitespace.')
        if parameters['reasoning_effort'] not in ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'):
            raise ValueError('Unsupported reasoning_effort value.')
        overrides = parameters.get('activity_overrides', {})
        validate_activity_overrides(overrides)
        prompts = profile['prompts']
        if not isinstance(prompts, dict) or set(prompts) != {'read', 'repair', 'final_check'}:
            raise ValueError('Prompts must specify read, repair and final_check.')
        if any(not isinstance(value, str) or not value.strip() for value in prompts.values()):
            raise ValueError('Every prompt must contain nonempty text.')
    except (ValueError, UnicodeError, TypeError, KeyError, ProfileError) as error:
        raise ProfileError('profile_invalid', f'Invalid OCR profile: {error}') from None
    return {'path': str(path), 'sha256': digest, 'text': text, 'profile': profile}


def ai_activity(activity):
    """Map trusted application phases to the four configurable AI activities."""
    if activity is None:
        return None
    if activity in ('reading', 'visual_reading', 'vision_diagnostic', 'context_diagnostic', 'check_account', 'login'):
        return 'reading'
    if activity in ('geometry', 'source_expectations', 'geometry_examination') or activity.startswith('geometry_'):
        return 'geometry'
    if activity in ('final_check', 'output_review', 'output_examination'):
        return 'final_check'
    if activity in ('repair', 'corrections') or activity.startswith('repair_'):
        return 'repair'
    raise ValueError('Unknown AI activity: ' + str(activity))


def validate_activity_overrides(overrides):
    if not isinstance(overrides, dict) or set(overrides) - set(AI_ACTIVITIES):
        raise ValueError('Activity overrides must name reading, geometry, final_check or repair.')
    for value in overrides.values():
        if not isinstance(value, dict) or set(value) != {'model', 'reasoning_effort'}:
            raise ValueError('An activity override must contain model and reasoning_effort.')
        model = value['model']
        if not isinstance(model, str) or not model.strip() or model != model.strip() or any(ord(c) < 32 for c in model):
            raise ValueError('An activity model must be a nonempty visible name.')
        if value['reasoning_effort'] not in ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'):
            raise ValueError('Unsupported activity reasoning_effort value.')


def effective_ai_settings(profile, activity=None):
    """Resolve the exact model pair from an already frozen run profile."""
    parameters = profile['parameters']
    selected = parameters.get('activity_overrides', {}).get(ai_activity(activity), parameters)
    return {key: selected[key] for key in ('model', 'reasoning_effort')}
