"""Five trace-only quality measurements; unsupported dimensions stay null.

Grounding: fraction of cited trace references resolving to nonempty source/tool
records. Path: fraction of inspected/candidate paths present in the inventory.
Verify: fraction of observed, source-referenced in-trial checks that pass with
resolvable references. Coherence: fraction of candidate transitions that retain
a candidate or introduce new evidence for its replacement. Efficiency: mean of
budget/(budget + observed total) across resource counters with configured
normalizers. These budgets are scale parameters, not measured optimal costs.
Each value reports its denominator, source fields and missingness; efficiency
also exposes totals/coverage. No scalar composite or outcome join is performed.
"""
from __future__ import annotations

from .conditions import QualityParameters
from .modules import repository_path_status
from .schema import Snapshot


def _metric(values: list[float], fields: tuple[str, ...], missing_reason: str,
            *, details: dict | None = None) -> dict:
    return {'value': sum(values) / len(values) if values else None,
            'observations': len(values), 'supported': bool(values),
            'missing_reason': None if values else missing_reason,
            'source_fields': list(fields), 'details': details or {}}


def measure_quality(snapshot: Snapshot, params: QualityParameters) -> dict:
    sources = {row.id: row for row in snapshot.evidence}
    refs = [ref for event in snapshot.history for ref in
            event.evidence_ref + (event.verifier.evidence_refs if event.verifier else ())]
    grounding = [float(ref in sources and bool(sources[ref].content.strip() or sources[ref].tool_ref))
                 for ref in refs]
    inspected = [path for event in snapshot.history for path in (event.object, event.candidate) if path]
    paths = ([float(repository_path_status(path, snapshot.repository_files)[0] == 'pass')
              for path in inspected] if snapshot.repository_files is not None else [])
    verification = []
    for event in snapshot.history:
        check = event.verifier
        if check is None or check.status == 'unknown' or not (check.tool_ref or check.evidence_refs):
            continue
        references_resolve = all(ref in sources and bool(sources[ref].content.strip() or sources[ref].tool_ref)
                                 for ref in check.evidence_refs)
        verification.append(float(check.status == 'pass' and references_resolve))
    coherence, seen, previous = [], set(), None
    for event in snapshot.history:
        current_refs = set(event.evidence_ref + (event.verifier.evidence_refs if event.verifier else ()))
        if event.candidate is not None:
            if previous is not None:
                new_support = any(ref in sources and (sources[ref].owner or sources[ref].path) == event.candidate
                    and bool(sources[ref].content.strip() or sources[ref].tool_ref)
                    and sources[ref].polarity == 'support' and sources[ref].verified is not False
                    for ref in current_refs - seen)
                coherence.append(float(previous == event.candidate or new_support))
            previous = event.candidate
        seen.update(current_refs)
    budgets = {'tokens': params.token_budget, 'calls': params.call_budget,
               'elapsed_ms': params.elapsed_ms_budget}
    totals, coverage, efficiency = {}, {}, []
    for field, budget in budgets.items():
        observations = [getattr(event.resource, field) for event in snapshot.history
                        if event.resource is not None and getattr(event.resource, field) is not None]
        totals[field] = sum(observations) if observations else None
        coverage[field] = {'observed_events': len(observations), 'total_events': len(snapshot.history)}
        if observations and budget is not None:
            efficiency.append(budget / (budget + sum(observations)))
    return {
        'grounding': _metric(grounding, ('history.evidence_ref', 'history.verifier.evidence_refs', 'evidence'),
                             'no_trace_evidence_references'),
        'path': _metric(paths, ('history.object', 'history.candidate', 'repository_files'),
                       'repository_inventory_unavailable' if snapshot.repository_files is None else 'no_trace_repository_paths'),
        'verify': _metric(verification, ('history.verifier', 'evidence'), 'no_source_referenced_verifier_checks'),
        'coherence': _metric(coherence, ('history.candidate', 'history.evidence_ref', 'evidence'),
                             'fewer_than_two_candidate_observations'),
        'efficiency': _metric(efficiency, ('history.resource',), 'no_resource_counter_with_registered_normalizer',
            details={'totals': totals, 'coverage': coverage, 'normalizers': budgets,
                     'rule': 'mean_budget_divided_by_budget_plus_observed_total'}),
    }

