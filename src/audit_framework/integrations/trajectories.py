"""Offline schema adapters for SWE-agent, mini-swe-agent and DeepSWE/ATIF.

Canonical events preserve raw indices and caller-provided task/trial IDs.
The snapshot bridge requires an explicit exclusive cutoff and caller-supplied
candidate associations. Verification is never derived from final run outcomes.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import re
from typing import Any

from .upstream import merge_mini_metadata


def _text(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
    raise ValueError('Trajectory text must be text, structured JSON, or null')


def _records(raw: dict, key: str) -> list[dict]:
    rows = raw.get(key)
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ValueError(f'{key}: expected an array of objects')
    return rows


def _action(row: dict) -> str:
    if row.get('action') is not None:
        return _text(row['action'])
    extra = row.get('extra') or {}
    if not isinstance(extra, dict):
        raise ValueError('message.extra: expected object')
    if extra.get('actions'):
        return _text(extra['actions'])
    if row.get('tool_calls'):
        return _text(row['tool_calls'])
    if row.get('role') == 'assistant':
        fence = chr(96) * 3
        matches = re.findall(fence + r'(?:bash|sh)\s*\n(.*?)' + fence,
                             _text(row.get('content')), re.S)
        return '\n'.join(matches)
    return ''


@dataclass(frozen=True)
class CanonicalEvent:
    id: str
    raw_index: int
    role: str
    context: str
    action: str
    observation: str
    tool_call_id: str | None = None


@dataclass(frozen=True)
class CanonicalTrajectory:
    task_id: str
    trial_id: str
    source: str
    format: str
    raw_count: int
    events: tuple[CanonicalEvent, ...]

    def as_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self), ensure_ascii=False, allow_nan=False))


def parse_trajectory(raw: dict, *, source: str, task_id: str,
                     trial_id: str = 'default') -> CanonicalTrajectory:
    """Normalize one trajectory without executing commands, grading, or fetching URLs."""
    if not isinstance(raw, dict):
        raise ValueError('Expected one trajectory object')
    if not all(isinstance(x, str) and x.strip() for x in (task_id, trial_id)):
        raise ValueError('Explicit task_id and trial_id are required')
    events = []
    if source in {'swe_agent', 'swe_bench_pro'}:
        rows = _records(raw, 'trajectory')
        format_name = 'swe-agent-trajectory'
        for i, row in enumerate(rows):
            events.append(CanonicalEvent(f'event:{i}', i, 'assistant',
                _text(row.get('thought', row.get('response'))),
                _text(row.get('action')), _text(row.get('observation'))))
    elif source in {'mini_swe_agent', 'deepswe'} and 'messages' in raw:
        rows = _records(raw, 'messages')
        format_name = raw.get('trajectory_format', 'mini-swe-agent-1.0')
        if format_name not in {'mini-swe-agent-1.0', 'mini-swe-agent-1.1'}:
            raise ValueError(f'Unsupported mini-swe-agent format: {format_name}')
        rows = merge_mini_metadata({'messages': deepcopy(rows)})['messages']
        for i, row in enumerate(rows):
            role = row.get('role')
            if role not in {'system', 'user', 'assistant', 'tool', 'exit'}:
                raise ValueError(f'Unknown message role at {i}')
            content = _text(row.get('content'))
            observation = content if role == 'tool' or (role == 'user' and i > 1) else ''
            events.append(CanonicalEvent(f'event:{i}', i, role,
                '' if observation else content, _action(row), observation, row.get('tool_call_id')))
    elif source == 'deepswe' and 'steps' in raw:
        rows = _records(raw, 'steps')
        format_name = 'deepswe-atif-steps'
        for i, row in enumerate(rows):
            role = row.get('source', row.get('role', 'unknown'))
            if not isinstance(role, str):
                raise ValueError(f'Invalid step source at {i}')
            events.append(CanonicalEvent(f'event:{i}', i, role,
                _text(row.get('message', row.get('content'))), _action(row),
                _text(row.get('observation')), row.get('tool_call_id')))
    else:
        raise ValueError('Unsupported source or trajectory structure')
    return CanonicalTrajectory(task_id, trial_id, source, format_name, len(rows), tuple(events))


def snapshot_from_trajectory(trajectory: CanonicalTrajectory, *, before_index: int,
                             candidates: list[dict], issue: str = '',
                             repository_files: list[str] | None = None,
                             model_config: dict | None = None) -> dict:
    """Build a core snapshot from a strictly pre-decision prefix.

Observations become unverified tool evidence observation:<raw_index>.
Candidate evidence_refs must be supplied explicitly using these IDs.
"""
    if type(before_index) is not int or not 0 <= before_index <= trajectory.raw_count:
        raise ValueError('before_index must be an exclusive raw-record cutoff')
    evidence, history = [], []
    for event in trajectory.events:
        if event.raw_index >= before_index:
            continue
        if event.role == 'exit':
            raise ValueError('Snapshot prefix contains a terminal outcome message')
        refs = []
        if event.observation:
            ref = f'observation:{event.raw_index}'
            refs.append(ref)
            evidence.append({'id': ref, 'kind': 'tool', 'content': event.observation,
                             'tool_ref': event.tool_call_id or event.id, 'verified': None})
        history.append({'id': event.id, 'task_id': trajectory.task_id, 'trial_id': trajectory.trial_id,
                        'context': event.context, 'action': event.action or None, 'evidence_ref': refs})
    snapshot = {'task_id': trajectory.task_id, 'trial_id': trajectory.trial_id,
                'issue': issue, 'candidates': deepcopy(candidates), 'evidence': evidence,
                'history': history, 'repository_files': deepcopy(repository_files),
                'model_config': deepcopy(model_config or {})}
    from ..schema import Snapshot
    return Snapshot.from_dict(snapshot).as_dict()
