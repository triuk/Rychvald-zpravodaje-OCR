"""Original native submission identities shared by admission and reconciliation.

A notification without its correlated request ACK never supplies a turn ID.
Consumers classify failure or inspect the provider; neither reparses identity.
"""
import copy
import json
from pathlib import Path
from typing import Literal, NamedTuple, TypedDict

from .jobs import JobError


class Submission(TypedDict):
    thread_id: str
    turn_id: str | None
    connection_id: str
    visual_stage: str | None
    request_id: int | str | None
    delivery_state: Literal['unknown', 'accepted', 'rejected', 'completed', 'failed', 'interrupted']
    original_error: dict | None


class OriginalProtocol(NamedTuple):
    submissions: list[Submission]
    malformed: bool


def read_original_protocol(path: Path) -> OriginalProtocol:
    pending, submitted, malformed = {}, [], False
    for line in path.read_text().splitlines(keepends=True):
        if not line.endswith('\n'):
            malformed = True
            continue
        try:
            row = json.loads(line)
        except ValueError:
            malformed = True
            continue
        message, connection = row['message'], str(row.get('connection_id', '0'))
        key = (connection, message.get('id'))
        if row['direction'] == 'client' and message.get('method') == 'turn/start':
            record: Submission = {'thread_id': message['params']['threadId'], 'turn_id': None,
                'connection_id': connection, 'visual_stage': row.get('stage'),
                'request_id': message.get('id'), 'delivery_state': 'unknown', 'original_error': None}
            pending[key] = record
            submitted.append(record)
        elif row['direction'] == 'server':
            if key in pending and 'method' not in message and row.get('stage') == pending[key]['visual_stage']:
                record = pending[key]
                if message.get('error'):
                    if record['turn_id'] is not None:
                        raise JobError('attempt_conflict', 'Original turn has conflicting acceptance/rejection evidence.')
                    record.update(delivery_state='rejected', original_error=copy.deepcopy(message['error']))
                elif message.get('result', {}).get('turn', {}).get('id'):
                    identifier = message['result']['turn']['id']
                    if record['delivery_state'] == 'rejected' or record['turn_id'] not in (None, identifier):
                        raise JobError('attempt_conflict', 'Original request has conflicting turn identities.')
                    record['turn_id'] = identifier
                    if record['delivery_state'] == 'unknown':
                        record['delivery_state'] = 'accepted'
            elif message.get('method') in ('turn/started', 'turn/completed'):
                params, terminal = message['params'], message['params']['turn']
                candidates = [record for record in submitted if record['connection_id'] == connection and
                    record['thread_id'] == params.get('threadId') and record['visual_stage'] == row.get('stage') and
                    record['delivery_state'] != 'rejected' and record['turn_id'] == terminal['id']]
                if len(candidates) == 1:
                    record = candidates[0]
                    known_terminal = record['delivery_state'] in ('completed', 'failed', 'interrupted')
                    if message['method'] == 'turn/completed':
                        if known_terminal and record['delivery_state'] != terminal['status']:
                            raise JobError('attempt_conflict', 'Original turn has conflicting terminal states.')
                        record.update(turn_id=terminal['id'], delivery_state=terminal['status'])
                        if terminal.get('error') and not known_terminal:
                            record['original_error'] = copy.deepcopy(terminal['error'])
                    elif not known_terminal:
                        record.update(turn_id=terminal['id'], delivery_state='accepted')
    return OriginalProtocol(submitted, malformed)
