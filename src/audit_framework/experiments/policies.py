"""Deterministic scheduling hooks; policies control when audits can change output."""
from __future__ import annotations
from copy import deepcopy
from .contracts import require

POLICIES = {
    'solver_only': 'solver',
    'end_of_run_audit': 'end',
    'evidence_grounded_intervention': 'evidence',
    'full_audit': 'full',
    'observe_only_audit': 'observe',
    'online_generic_intervention': 'online',
}
SOURCE_POLICIES = dict(zip(POLICIES, ('solver_only', 'solver_plus_end_of_run_audit',
    'solver_plus_evidence_grounded_intervention', 'solver_plus_full_shenji',
    'solver_plus_observe_only_shenji', 'solver_plus_online_generic_intervention')))


def audit_schedule(policy: str, *, stage: str, evidence_changed: bool = False,
                   checkpoint_index: int = 0, interval: int = 1) -> dict:
    require(policy in POLICIES, f'Unknown audit policy: {policy}')
    require(stage in {'checkpoint', 'final'}, 'Unknown scheduling stage')
    require(type(interval) is int and interval > 0, 'Audit interval must be positive')
    kind = POLICIES[policy]
    due = stage == 'final' or checkpoint_index % interval == 0
    audit = kind != 'solver' and ((kind == 'end' and stage == 'final') or
            (kind in {'observe', 'full', 'online'} and due) or
            (kind == 'evidence' and evidence_changed and due))
    return {'audit': audit, 'intervene': audit and kind not in {'solver', 'observe'},
            'observe_only': kind == 'observe', 'policy': policy, 'stage': stage}


def apply_scheduled_decision(solver: dict, audited: dict | None, schedule: dict) -> dict:
    if schedule['intervene']:
        require(audited is not None, 'Scheduled intervention requires an actual audit result')
        return deepcopy(audited)
    return deepcopy(solver)
