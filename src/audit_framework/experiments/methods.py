"""Candidate fusion adapted from the supplied pro_localization implementation.

Ownership weights, the v3_ownership profile and tool anchoring preserve the
supplied source algorithms. Retrieval construction is explicit in adapters.py.
"""
from __future__ import annotations
from copy import deepcopy
import json
import re
from .contracts import require

WEIGHTS = {'path_score': .10, 'content_score': .20, 'one_shot_score': .10,
           'tool_score': .20, 'symbol_score': .10, 'source_agreement': .15,
           'ownership_score': .15}


def add_ownership(scored: list[dict]) -> None:
    for row in scored:
        row['ownership_score'] = round(min(1., .20 * int(row.get('source_count', 0))
            + .15 * int(int(row.get('tool_reads', 0)) > 0)
            + .15 * int(not row.get('is_test_like'))
            + .10 * int(not row.get('is_doc_like'))
            + .10 * int(not row.get('is_generated_like'))), 6)


def weighted_ranking(scored: list[dict], weights: dict | None = None) -> list[dict]:
    profile = WEIGHTS if weights is None else weights
    require(set(profile) == set(WEIGHTS), 'Fusion profile must name all seven features')
    rows = deepcopy(scored)
    for row in rows:
        row['base_score'] = round(sum(float(row.get(k, 0) or 0) * v for k, v in profile.items()), 6)
    rows.sort(key=lambda r: (-r['base_score'], r['candidate_file']))
    for rank, row in enumerate(rows, 1):
        row['base_rank'] = rank
    return rows


def tool_anchor(scored: list[dict], tool_paths: list[str]) -> list[dict]:
    rows = deepcopy(scored)
    inspected = {path: i for i, path in enumerate(tool_paths)}
    rows.sort(key=lambda r: (0 if r['candidate_file'] in inspected else 1,
        inspected.get(r['candidate_file'], 10**6), -float(r.get('base_score', 0)), r['candidate_file']))
    for rank, row in enumerate(rows, 1):
        row['base_rank'] = rank
    return rows


def score_candidates(candidates: list[dict], direct: list[str], tool: list[str],
                     trace: list[dict]) -> list[dict]:
    """Port of cross_dataset_localization.score_candidates for relative paths."""
    by_path = {}
    max_path = max([float(r.get('path_score') or 0) for r in candidates] or [1.])
    max_content = max([int(r.get('content_hits') or 0) for r in candidates] or [1])
    trace_text = json.dumps(trace, ensure_ascii=False).lower()
    for row in candidates:
        path = row['repo_relative']
        direct_rank = direct.index(path) + 1 if path in direct else 0
        tool_rank = tool.index(path) + 1 if path in tool else 0
        reads = trace_text.count(f'"path": "{path.lower()}"')
        search_hits = trace_text.count(path.lower())
        sources = ['blind_retrieval']
        if int(row.get('content_hits') or 0): sources.append('code_content')
        if direct_rank: sources.append('one_shot')
        if tool_rank: sources.append('tool_search')
        if reads: sources.append('file_read')
        by_path[path] = {
            'candidate_file': path, 'path_score': round(float(row.get('path_score') or 0) / max(1., max_path), 6),
            'content_score': round(int(row.get('content_hits') or 0) / max(1, max_content), 6),
            'one_shot_score': round(1. / direct_rank if direct_rank else 0., 6),
            'tool_score': round(min(1., (1. / tool_rank if tool_rank else 0.) + min(.25, reads * .08 + search_hits * .01)), 6),
            'symbol_score': round(min(1., search_hits / 4.), 6),
            'source_agreement': round(min(1., max(0, len(sources) - 1) / 3.), 6),
            'source_count': len(sources), 'tool_reads': reads,
            'is_test_like': bool(re.search(r'(^|/)(test|tests|spec|fixtures?)(/|_|\.)', path, re.I)),
            'is_doc_like': bool(re.search(r'(^|/)(docs?|readme|changelog)(/|\.|$)|\.(md|rst)$', path, re.I)),
            'is_generated_like': bool(re.search(r'(^|/)(vendor|generated|dist|third_party)(/|$)', path, re.I)),
        }
    rows = list(by_path.values())
    add_ownership(rows)
    return weighted_ranking(rows)


def selected_paths(result: dict) -> list[str]:
    if 'decision' in result:
        return list(result['decision'].get('ranking', []))
    return [item['path'] for item in result.get('files', [])]


def trust_first(snapshot: dict, audit: dict, anchored_ranking: list[str] | None = None) -> dict:
    """Evidence, inspection, owner/path and critical-failure gate; no outcome labels."""
    # The controller establishes eligibility, not the trust-first preference order.
    # Feeding reordered candidates back through it would erase the tool anchor.
    eligible = set(audit['decision'].get('ranking', []))
    ranking = list(anchored_ranking if anchored_ranking is not None else
                   [c['path'] for c in snapshot.get('candidates', [])])
    if len(ranking) != len(set(ranking)):
        raise ValueError('Duplicate anchored candidate')
    evidence = {e['id']: e for e in snapshot.get('evidence', [])}
    checks, accepted = {}, []
    for path in ranking:
        candidate = next((c for c in snapshot.get('candidates', []) if c['path'] == path), None)
        supported = bool(candidate and any(ref in evidence and evidence[ref].get('path') == path
                                          for ref in candidate.get('evidence_refs', [])))
        inspected = any(h.get('action') in {'read_file', 'search_text', 'find_symbol', 'repository_observation'}
                        and path in {h.get('object'), h.get('candidate')}
                        and any(ref in evidence for ref in h.get('evidence_ref', []))
                        for h in snapshot.get('history', []))
        assessments = {name: next((a for a in output['assessments'] if a['candidate'] == path), None)
                       for name, output in audit.get('module_outputs', {}).items()}
        owner_path = all(assessments.get(name) and assessments[name]['verdict'] == 'pass'
                         for name in ('ownership', 'path_verification'))
        critical = any(a and a['verdict'] == 'fail' for a in assessments.values())
        valid = bool(path in eligible and supported and inspected and owner_path and not critical)
        checks[path] = {'evidence': supported, 'inspection': inspected, 'owner_path': bool(owner_path),
                        'critical_failure': critical, 'controller_eligible': path in eligible, 'valid': valid}
        if valid:
            accepted.append(path)
    return {'files': [{'path': p} for p in accepted],
            'retained_candidates': ranking, 'process_valid': bool(accepted), 'abstained': not accepted,
            'process_checks': checks,
            'audit': deepcopy(audit)}
