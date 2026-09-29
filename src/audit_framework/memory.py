"""Persistent *within-trial* evidence memory, with immutable append/update states.

EvidenceMemory.remember returns a new state; callers can retain it across steps.
The JSON engine reconstructs exactly that state by replaying declared history,
so evaluation order and other tasks cannot contaminate a run. Only referenced
source Evidence is retained. There are no gold, rank, success or cohort inputs.
Unresolved references are not fabricated. A memory entry cites its source event.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .schema import Evidence, Snapshot, TraceEvent


@dataclass(frozen=True)
class MemoryEntry:
    candidate: str
    evidence: Evidence
    first_event: str
    last_event: str
    occurrences: int = 1


@dataclass(frozen=True)
class EvidenceMemory:
    task_id: str
    trial_id: str
    entries: tuple[MemoryEntry, ...] = ()

    def remember(self, event: TraceEvent, evidence: tuple[Evidence, ...]) -> EvidenceMemory:
        if (event.task_id, event.trial_id) != (self.task_id, self.trial_id):
            raise ValueError('memory cannot cross task/trial boundaries')
        sources = {item.id: item for item in evidence}
        references = tuple(dict.fromkeys(event.evidence_ref +
            (event.verifier.evidence_refs if event.verifier else ())))
        retained = {(entry.candidate, entry.evidence.id): entry for entry in self.entries}
        known_sources = {entry.evidence.id: entry.evidence for entry in self.entries}
        for ref in references:
            item = sources.get(ref)
            if item is None or not (item.content.strip() or item.tool_ref):
                continue
            if item.id in known_sources and known_sources[item.id] != item:
                raise ValueError('an evidence id cannot change its source contents')
            candidate = event.candidate or item.owner or item.path
            if candidate is None:
                continue
            key = (candidate, item.id)
            if key in retained:
                previous = retained[key]
                if previous.evidence != item:
                    raise ValueError('an evidence id cannot change its source contents')
                retained[key] = replace(previous, last_event=event.id, occurrences=previous.occurrences + 1)
            else:
                retained[key] = MemoryEntry(candidate, item, event.id, event.id)
        return EvidenceMemory(self.task_id, self.trial_id, tuple(retained[k] for k in sorted(retained)))

    @classmethod
    def from_snapshot(cls, snapshot: Snapshot) -> EvidenceMemory:
        memory = cls(snapshot.task_id, snapshot.trial_id)
        for event in snapshot.history:
            memory = memory.remember(event, snapshot.evidence)
        return memory
