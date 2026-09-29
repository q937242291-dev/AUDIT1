"""Local tool-feedback formatting and task-scoped memory references.

CRITIC prompt layout is adapted from Microsoft ProphetNet's CRITIC program
critic, Copyright (c) Microsoft Corporation, MIT license retained at
third_party/critic/LICENSE. The shell/tool adaptation is authored here.
Memory selection is an original implementation informed by the cited memory
papers, with no HiAgent, Reflexion, or AgeMem source copied.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from .upstream import source_info, verified_path


@dataclass(frozen=True)
class ToolFeedback:
    task_id: str
    trial_id: str
    evidence_id: str
    tool_ref: str
    command: str
    observation: str
    exit_code: int | None = None


def build_critic_feedback(question: str, proposal: str, feedback: ToolFeedback) -> dict:
    """Build a critique input from an already-observed tool result, without calling tools."""
    if not all(isinstance(x, str) and x.strip() for x in
               (feedback.task_id, feedback.trial_id, feedback.evidence_id, feedback.tool_ref, feedback.command)):
        raise ValueError('Feedback needs explicit task/trial identity, command and evidence references')
    if not isinstance(question, str) or not isinstance(proposal, str) or not isinstance(feedback.observation, str):
        raise ValueError('Question, proposal and observation must be strings')
    if feedback.exit_code is not None and type(feedback.exit_code) is not int:
        raise ValueError('exit_code must be an observed integer or null')
    verified_path('critic', 'CRITIC/src/program/critic.py')
    status = 'unknown' if feedback.exit_code is None else ('pass' if feedback.exit_code == 0 else 'fail')
    # Preserve CRITIC's Question / proposal / Execution / Output / critique sequence.
    prompt = (f'Question: {question}\nProposed localization: {proposal}\n'
              f'Execution: {feedback.command}\nOutput: {feedback.observation}\n'
              "\nWhat's the problem with the above localization?\n"
              'Use only the supplied observation and cite its evidence identifier.\n'
              f'Evidence identifier: {feedback.evidence_id}\n')
    return {'prompt': prompt,
            'evidence': {'id': feedback.evidence_id, 'kind': 'tool',
                         'content': feedback.observation, 'tool_ref': feedback.tool_ref,
                         'verified': None},
            'verifier': {'status': status, 'evidence_refs': [feedback.evidence_id],
                         'tool_ref': feedback.tool_ref, 'detail': 'In-trial tool process exit only; no final repair outcome'},
            'source': {'repository': source_info('critic')['repository'],
                       'commit': source_info('critic')['commit'], 'reuse': 'adapted_prompt_layout'}}


def select_task_memory(episodes: list[dict], *, task_id: str, trial_id: str,
                       before_index: int, limit: int = 8) -> list[dict]:
    """Return only prior, evidence-backed episodes from the same task and trial.

Schema: task_id, trial_id, event_index, summary, evidence_refs.
This selects supplied summaries; it does not generate or learn reflections.
"""
    if type(before_index) is not int or before_index < 0 or type(limit) is not int or limit < 0:
        raise ValueError('Cutoff and limit must be nonnegative integers')
    from ..boundary import check_boundary
    check_boundary(episodes)
    selected = []
    seen = set()
    for episode in episodes:
        required = {'task_id', 'trial_id', 'event_index', 'summary', 'evidence_refs'}
        if not isinstance(episode, dict) or set(episode) != required:
            raise ValueError('Unregistered memory episode schema')
        index, refs = episode['event_index'], episode['evidence_refs']
        if type(index) is not int or index < 0 or not isinstance(episode['summary'], str):
            raise ValueError('Invalid memory index or summary')
        if not isinstance(refs, list) or not refs or any(not isinstance(r, str) or not r for r in refs):
            raise ValueError('Memory must cite nonempty evidence identifiers')
        key = (episode['task_id'], episode['trial_id'], index)
        if key in seen:
            raise ValueError('Duplicate task/trial memory index')
        seen.add(key)
        if key[:2] == (task_id, trial_id) and index < before_index:
            selected.append(deepcopy(episode))
    selected.sort(key=lambda x: x['event_index'])
    return selected[-limit:] if limit else []
