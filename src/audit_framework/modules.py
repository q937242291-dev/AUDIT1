"""Seven independent modules over one immutable source snapshot.

No module reads another module's output, and no module is condition-aware.
Each assessment cites evidence, tool and event references. Grounding checks
reference resolution/content, ownership checks explicit owner or source path,
contradiction checks observed polarity/claim/contradicts relations, detour checks
repeated exploration without new evidence, path_verification checks canonical
paths against the supplied inventory, memory replays trial evidence, and
abstention checks a configured minimum of available evidence references.

These are deterministic operationalizations of the registered checks. Explicit verified/owner/claim
annotations must be agent-visible tool observations, never evaluator labels.
"""
from __future__ import annotations

from dataclasses import asdict

from .conditions import ModuleParameters
from .memory import EvidenceMemory
from .schema import (Assessment, Candidate, Evidence, IMPLEMENTATION_VERSION,
                     MODULE_NAMES, ModuleOutput, ModuleProvenance, Snapshot, digest)


def repository_path_status(path: str, repository_files: tuple[str, ...] | None) -> tuple[str, str]:
    """No filesystem access. Reject drive/UNC/traversal/noncanonical paths."""
    if (not path or path.startswith('/') or '\\' in path or ':' in path
            or any(ord(char) < 32 or ord(char) == 127 for char in path)
            or any(part in {'', '.', '..'} for part in path.split('/'))):
        return 'fail', 'noncanonical_repository_relative_path'
    if repository_files is None:
        return 'unknown', 'repository_inventory_unavailable'
    if path not in repository_files:
        return 'fail', 'path_absent_from_repository_inventory'
    return 'pass', 'path_present_in_repository_inventory'


def _available(item: Evidence) -> bool:
    return bool(item.content.strip() or item.tool_ref)


def _refs(candidate: Candidate, snapshot: Snapshot) -> tuple[tuple[Evidence, ...], tuple[str, ...]]:
    source = {item.id: item for item in snapshot.evidence}
    refs = tuple(dict.fromkeys(candidate.evidence_refs))
    return tuple(source[ref] for ref in refs if ref in source), tuple(ref for ref in refs if ref not in source)


def _assessment(candidate: Candidate, verdict: str, score: float, reasons: tuple[str, ...],
                rows: tuple[Evidence, ...] = (), *, refs: tuple[str, ...] = (),
                events: tuple[str, ...] = ()) -> Assessment:
    return Assessment(candidate.path, verdict, score, reasons,
        tuple(sorted(set(refs) | {row.id for row in rows})),
        tuple(sorted({row.tool_ref for row in rows if row.tool_ref})), tuple(sorted(set(events))))


def _grounding(candidate: Candidate, snapshot: Snapshot, params: ModuleParameters) -> Assessment:
    rows, unresolved = _refs(candidate, snapshot)
    if unresolved:
        return _assessment(candidate, 'fail', 0.0, ('unresolved_evidence_reference',), rows, refs=unresolved)
    if not rows:
        return _assessment(candidate, 'unknown', 0.0, ('no_grounding_evidence',))
    usable = tuple(row for row in rows if _available(row) and row.verified is not False)
    failed = len(usable) != len(rows) or len(usable) < params.minimum_grounding_refs
    return _assessment(candidate, 'fail' if failed else 'pass',
        0.0 if failed else len(usable) / (len(usable) + 1),
        ('missing_or_rejected_source_evidence' if failed else 'source_references_resolve',), rows)


def _ownership(candidate: Candidate, snapshot: Snapshot, params: ModuleParameters) -> Assessment:
    rows, _ = _refs(candidate, snapshot)
    owned = tuple(row for row in rows if row.owner is not None or row.path is not None)
    if not owned:
        return _assessment(candidate, 'unknown', 0.0, ('ownership_unobserved',), rows)
    matches = tuple(row for row in owned if (row.owner or row.path) == candidate.path)
    failed = len(matches) != len(owned)
    return _assessment(candidate, 'fail' if failed else 'pass', 0.0 if failed else 1.0,
        ('source_owned_by_different_candidate' if failed else 'candidate_owns_cited_source',), owned)


def _contradiction(candidate: Candidate, snapshot: Snapshot, params: ModuleParameters) -> Assessment:
    rows, _ = _refs(candidate, snapshot)
    if not rows:
        return _assessment(candidate, 'unknown', 0.0, ('no_assertions_to_compare',))
    cited = {row.id for row in rows}
    claims = {row.claim for row in rows if row.claim}
    related = tuple(row for row in snapshot.evidence if row.id in cited
        or any(ref in cited for ref in row.contradicts)
        or any(row.id in item.contradicts for item in rows)
        or (row.claim in claims and (row.owner or row.path) == candidate.path))
    related_ids = {row.id for row in related}
    conflict = any(row.polarity == 'oppose' for row in related)
    conflict |= any(set(row.contradicts) & related_ids for row in related)
    return _assessment(candidate, 'fail' if conflict else 'pass', 0.0 if conflict else 1.0,
        ('contradictory_source_assertion' if conflict else 'no_observed_contradiction',), related)


def _detour(candidate: Candidate, snapshot: Snapshot, params: ModuleParameters) -> Assessment:
    events = tuple(event for event in snapshot.history[-params.detour_window:]
                   if event.candidate == candidate.path or event.object == candidate.path)
    if not events:
        return _assessment(candidate, 'unknown', 0.0, ('exploration_history_unavailable',))
    sources = {row.id: row for row in snapshot.evidence}
    seen, productive, cited = set(), 0, set()
    for event in events:
        refs = event.evidence_ref + (event.verifier.evidence_refs if event.verifier else ())
        useful = {ref for ref in refs if ref in sources and _available(sources[ref])
                  and (sources[ref].owner or sources[ref].path) == candidate.path}
        if useful - seen:
            productive += 1
        seen.update(useful)
        cited.update(refs)
    repeated = len(events) - productive
    failed = repeated >= params.detour_repeat_threshold
    verdict = 'fail' if failed else ('pass' if productive else 'unknown')
    return _assessment(candidate, verdict, productive / len(events) if verdict == 'pass' else 0.0,
        ('repeated_exploration_without_new_evidence' if failed else
         'exploration_adds_evidence' if productive else 'no_new_evidence_yet',),
        tuple(sources[ref] for ref in cited if ref in sources), refs=tuple(cited),
        events=tuple(event.id for event in events))


def _path_verification(candidate: Candidate, snapshot: Snapshot, params: ModuleParameters) -> Assessment:
    rows, _ = _refs(candidate, snapshot)
    checks = [repository_path_status(candidate.path, snapshot.repository_files)]
    checks.extend(repository_path_status(row.path, snapshot.repository_files) for row in rows if row.path)
    verdict = 'fail' if any(status == 'fail' for status, _ in checks) else (
        'unknown' if any(status == 'unknown' for status, _ in checks) else 'pass')
    return _assessment(candidate, verdict, 1.0 if verdict == 'pass' else 0.0,
                       tuple(sorted({reason for _, reason in checks})), rows)


def _memory(candidate: Candidate, snapshot: Snapshot, params: ModuleParameters,
            memory: EvidenceMemory) -> Assessment:
    entries = tuple(entry for entry in memory.entries if entry.candidate == candidate.path)
    if not entries:
        return _assessment(candidate, 'unknown', 0.0, ('no_retained_trial_evidence',))
    rows = tuple(entry.evidence for entry in entries)
    negative = any(row.polarity == 'oppose' or row.verified is False for row in rows)
    support = tuple(row for row in rows if row.polarity == 'support' and row.verified is not False
                    and (row.owner or row.path) == candidate.path)
    verdict = 'fail' if negative else ('pass' if support else 'unknown')
    return _assessment(candidate, verdict, len(support) / (len(support) + 1) if verdict == 'pass' else 0.0,
        ('retained_counterevidence' if negative else 'retained_trial_support' if support else
         'retained_evidence_without_candidate_support',), rows,
        events=tuple(event_id for entry in entries for event_id in (entry.first_event, entry.last_event)))


def _abstention(candidate: Candidate, snapshot: Snapshot, params: ModuleParameters) -> Assessment:
    rows, _ = _refs(candidate, snapshot)
    # Independent sufficiency check, not a call to grounding or memory.
    available = tuple(row for row in rows if _available(row))
    enough = len(available) >= params.minimum_abstention_refs
    return _assessment(candidate, 'pass' if enough else 'fail', 1.0 if enough else 0.0,
        ('minimum_evidence_available' if enough else 'insufficient_evidence',), rows)


_SOURCE_FIELDS = {
    'grounding': ('candidates.evidence_refs', 'evidence.id', 'evidence.content', 'evidence.tool_ref', 'evidence.verified'),
    'ownership': ('candidates.path', 'candidates.evidence_refs', 'evidence.owner', 'evidence.path'),
    'contradiction': ('candidates.evidence_refs', 'evidence.claim', 'evidence.polarity', 'evidence.contradicts', 'evidence.owner', 'evidence.path'),
    'detour': ('history.candidate', 'history.object', 'history.evidence_ref', 'history.verifier.evidence_refs', 'evidence'),
    'path_verification': ('candidates.path', 'candidates.evidence_refs', 'evidence.path', 'repository_files'),
    'memory': ('task_id', 'trial_id', 'history', 'evidence'),
    'abstention': ('candidates.evidence_refs', 'evidence.id', 'evidence.content', 'evidence.tool_ref'),
}
_FUNCTIONS = {'grounding': _grounding, 'ownership': _ownership, 'contradiction': _contradiction,
              'detour': _detour, 'path_verification': _path_verification, 'abstention': _abstention}


def run_modules(snapshot: Snapshot, params: ModuleParameters) -> tuple[ModuleOutput, ...]:
    """Compute all seven outputs exactly once, without any condition argument."""
    memory = EvidenceMemory.from_snapshot(snapshot)
    source_digest, parameters_digest = snapshot.digest(), digest(asdict(params))
    outputs = []
    for name in MODULE_NAMES:
        assessments = tuple(_memory(candidate, snapshot, params, memory) if name == 'memory'
            else _FUNCTIONS[name](candidate, snapshot, params) for candidate in snapshot.candidates)
        supportive = sorted((item for item in assessments if item.verdict == 'pass'),
                            key=lambda item: (-item.score, item.candidate))
        abstain = name == 'abstention' and not supportive
        vote = supportive[0].candidate if supportive else None
        outputs.append(ModuleOutput(name, assessments, vote, abstain,
            ModuleProvenance(IMPLEMENTATION_VERSION, source_digest, parameters_digest, _SOURCE_FIELDS[name])))
    return tuple(outputs)
