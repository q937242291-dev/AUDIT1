"""Controllers take candidate identifiers and ENABLED outputs, never raw evidence.

Full: remove candidates explicitly failed by enabled configured hard vetoes or
by an enabled abstention output. Rank survivors lexicographically by enabled
module scores in configured evidence precedence; use repository path for ties.
Unknown is not failure. No eligible candidate means abstain only when an enabled
abstention output caused exclusion; otherwise return blocked/no_candidate.

Majority: one equally weighted ballot per non-neutral module. Count the module's
candidate vote or explicit abstention vote. The registered rule is plurality
(often called majority voting), with lexical candidate ties and abstention first
on equal tallies. Report strict_majority separately so a plurality/tie is never
misrepresented as >50% agreement. No full-controller gates are applied here.

All aggregation inputs are explicit; disabled outputs contribute no scores,
gates, flags, ballots or tie-breaking information.
"""
from __future__ import annotations

from collections import Counter
import math

from .conditions import ControllerParameters
from .schema import MODULE_NAMES, ModuleOutput


def _checked(candidates: tuple[str, ...], outputs: tuple[ModuleOutput, ...]) -> dict:
    if len(candidates) != len(set(candidates)):
        raise ValueError('candidate identifiers must be unique')
    by_module = {}
    for output in outputs:
        if output.module not in MODULE_NAMES or output.module in by_module:
            raise ValueError('unregistered or duplicate module output')
        assessments = {item.candidate: item for item in output.assessments}
        if set(assessments) != set(candidates) or len(assessments) != len(output.assessments):
            raise ValueError('module assessments must cover each candidate exactly once')
        for item in assessments.values():
            if item.verdict not in {'pass', 'fail', 'unknown'} or not math.isfinite(item.score) or not 0 <= item.score <= 1:
                raise ValueError('invalid assessment verdict/score')
        if output.vote is not None and (output.vote not in assessments or assessments[output.vote].verdict != 'pass'):
            raise ValueError('module vote must cite a passed candidate assessment')
        if output.abstain and (output.module != 'abstention' or output.vote is not None):
            raise ValueError('only abstention can cast an abstention ballot')
        by_module[output.module] = assessments
    return by_module


def full_controller(candidates: tuple[str, ...], outputs: tuple[ModuleOutput, ...],
                    params: ControllerParameters) -> dict:
    by_module = _checked(candidates, outputs)
    excluded = {}
    for path in candidates:
        reasons = [name for name in params.hard_veto_modules if name in by_module
                   and by_module[name][path].verdict == 'fail']
        if 'abstention' in by_module and by_module['abstention'][path].verdict == 'fail':
            reasons.append('abstention')
        if reasons:
            excluded[path] = reasons
    precedence = tuple(name for name in params.evidence_precedence if name in by_module)
    ranking = sorted((path for path in candidates if path not in excluded),
        key=lambda path: tuple(-by_module[name][path].score for name in precedence) + (path,))
    if ranking:
        action, selected, reason = 'select', ranking[0], 'enabled_evidence_precedence'
    elif not candidates:
        action, selected, reason = 'no_candidate', None, 'empty_candidate_set'
    elif any('abstention' in reasons for reasons in excluded.values()):
        action, selected, reason = 'abstain', None, 'insufficient_evidence_for_eligible_candidate'
    else:
        action, selected, reason = 'blocked', None, 'enabled_hard_vetoes_reject_all_candidates'
    return {'controller': 'full', 'action': action, 'candidate': selected, 'ranking': ranking,
            'reason': reason, 'excluded': excluded, 'evidence_precedence': list(precedence)}


def majority_controller(candidates: tuple[str, ...], outputs: tuple[ModuleOutput, ...],
                        params: ControllerParameters) -> dict:
    _checked(candidates, outputs)
    counts, ballots = Counter(), []
    for output in outputs:
        if output.abstain:
            counts[None] += 1
            ballots.append({'module': output.module, 'vote': None, 'kind': 'abstain'})
        elif output.vote is not None:
            counts[output.vote] += 1
            ballots.append({'module': output.module, 'vote': output.vote, 'kind': 'candidate'})
    candidate_ranking = sorted(candidates, key=lambda path: (-counts[path], path))
    if not counts:
        action, winner, reason = ('no_candidate' if not candidates else 'no_votes'), None, 'no_candidate_ballots'
    else:
        winner = sorted(counts, key=lambda path: (-counts[path], 0 if path is None else 1, path or ''))[0]
        action = 'abstain' if winner is None else 'select'
        reason = 'module_ballot_plurality_with_registered_stable_ties'
    winner_votes = counts[winner] if counts else 0
    return {'controller': 'majority', 'action': action, 'candidate': winner,
            'ranking': candidate_ranking if action == 'select' else [],
            'candidate_ranking': candidate_ranking, 'reason': reason, 'ballots': ballots,
            'vote_counts': {path: counts[path] for path in sorted(candidates)},
            'abstain_votes': counts[None], 'votes_cast': len(ballots),
            'winner_votes': winner_votes, 'strict_majority': winner_votes > len(ballots) / 2,
            'vote_rule': params.vote_rule}


def aggregate(candidates: tuple[str, ...], outputs: tuple[ModuleOutput, ...],
              controller: str, params: ControllerParameters) -> dict:
    if controller == 'full':
        return full_controller(candidates, outputs, params)
    if controller == 'majority':
        return majority_controller(candidates, outputs, params)
    raise ValueError(f'unknown controller {controller!r}')
