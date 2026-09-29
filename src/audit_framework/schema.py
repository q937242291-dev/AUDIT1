"""Immutable JSON input/output types for the deterministic AUDIT core.

Snapshot keys (all unknown keys rejected recursively):
  task_id: required nonempty string; trial_id: string, default 'default'.
  issue/context: optional strings, default ''.
  candidates: list of {path: str, evidence_refs: [str]=[], score: number=0,
                      rationale: str=''}; paths must be unique.
  evidence: list of {id: str, path: str|null=null, content: str='',
     kind: 'source'|'tool'|'verification'='source', tool_ref: str|null=null,
     owner: str|null=null, claim: str|null=null,
     polarity: 'support'|'oppose'|'neutral'='support', verified: bool|null=null,
     contradicts: [evidence_id]=[]}; ids unique. 'owner' is a repository path,
     'claim' a source assertion identifier; neither is an evaluator label.
  history: chronological list of {id: str, task_id/trial_id: optional str
     matching snapshot, context/action/object/candidate: str|null=null,
     evidence_ref: str|[str]=[], verifier: null|{status: 'pass'|'fail'|'unknown',
       evidence_refs: [str]=[], tool_ref: str|null=null, detail: str=''},
     resource: null|{tokens: number>=0, calls: number>=0, elapsed_ms: number>=0}}.
     Verifiers describe in-trial source/tool checks, NEVER final repair success.
  repository_files: [str]|null, default null. null means inventory unavailable;
     [] means an available empty inventory. Paths are case-sensitive repository
     relative POSIX paths. Invalid candidate paths are audited, not normalized.
  model_config: {model/provider/reasoning_effort: optional str, temperature: optional number>=0,
                 seed/max_tokens: optional int>=0}; metadata only, no calls.
  candidates/evidence/history default []; model_config defaults {}.

Frozen dataclasses contain tuples and primitive values only. Source content is
not mutated, silently dropped, joined to outcomes, or interpreted as Python.
Detailed scoring choices are defined by the artifact configuration.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any

from .boundary import BoundaryError, allowed_object, check_boundary

MODULE_NAMES = ("grounding", "ownership", "contradiction", "detour",
                "path_verification", "memory", "abstention")
IMPLEMENTATION_VERSION = "audit_framework_v1"


def _text(value: Any, path: str, *, optional: bool = False, empty: bool = False):
    if optional and value is None:
        return None
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise BoundaryError(f"{path}: expected {'optional ' if optional else ''}string")
    return value


def _number(value: Any, path: str, *, nonnegative: bool = False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BoundaryError(f"{path}: expected number")
    if nonnegative and value < 0:
        raise BoundaryError(f"{path}: expected nonnegative number")
    return value


def _sequence(value: Any, path: str) -> list:
    if not isinstance(value, list):
        raise BoundaryError(f"{path}: expected list")
    return value


def _strings(value: Any, path: str) -> tuple[str, ...]:
    return tuple(_text(v, f"{path}[{i}]") for i, v in enumerate(_sequence(value, path)))


@dataclass(frozen=True)
class Candidate:
    path: str
    evidence_refs: tuple[str, ...] = ()
    score: float = 0.0
    rationale: str = ""


@dataclass(frozen=True)
class Evidence:
    id: str
    path: str | None = None
    content: str = ""
    kind: str = "source"
    tool_ref: str | None = None
    owner: str | None = None
    claim: str | None = None
    polarity: str = "support"
    verified: bool | None = None
    contradicts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Verifier:
    status: str
    evidence_refs: tuple[str, ...] = ()
    tool_ref: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class Resource:
    tokens: float | None = None
    calls: float | None = None
    elapsed_ms: float | None = None


@dataclass(frozen=True)
class TraceEvent:
    id: str
    task_id: str
    trial_id: str
    context: str | None = None
    action: str | None = None
    object: str | None = None
    candidate: str | None = None
    evidence_ref: tuple[str, ...] = ()
    verifier: Verifier | None = None
    resource: Resource | None = None


@dataclass(frozen=True)
class Snapshot:
    task_id: str
    trial_id: str
    issue: str
    context: str
    candidates: tuple[Candidate, ...]
    evidence: tuple[Evidence, ...]
    history: tuple[TraceEvent, ...]
    repository_files: tuple[str, ...] | None
    model_config: tuple[tuple[str, Any], ...]

    @classmethod
    def from_dict(cls, raw: dict) -> Snapshot:
        check_boundary(raw)
        row = allowed_object(raw, {"task_id", "trial_id", "issue", "context",
            "candidates", "evidence", "history", "repository_files", "model_config"},
            {"task_id"}, "snapshot")
        task = _text(row["task_id"], "task_id")
        trial = _text(row.get("trial_id", "default"), "trial_id")
        candidates = []
        for i, item in enumerate(_sequence(row.get("candidates", []), "candidates")):
            p = f"candidates[{i}]"
            c = allowed_object(item, {"path", "evidence_refs", "score", "rationale"}, {"path"}, p)
            candidates.append(Candidate(_text(c["path"], p + ".path"),
                _strings(c.get("evidence_refs", []), p + ".evidence_refs"),
                _number(c.get("score", 0), p + ".score"),
                _text(c.get("rationale", ""), p + ".rationale", empty=True)))
        evidence = []
        for i, item in enumerate(_sequence(row.get("evidence", []), "evidence")):
            p = f"evidence[{i}]"
            e = allowed_object(item, {"id", "path", "content", "kind", "tool_ref",
                "owner", "claim", "polarity", "verified", "contradicts"}, {"id"}, p)
            if e.get("kind", "source") not in ("source", "tool", "verification"):
                raise BoundaryError(p + ".kind: unregistered evidence kind")
            if e.get("polarity", "support") not in ("support", "oppose", "neutral"):
                raise BoundaryError(p + ".polarity: invalid polarity")
            if e.get("verified") is not None and type(e["verified"]) is not bool:
                raise BoundaryError(p + ".verified: expected bool or null")
            evidence.append(Evidence(
                _text(e["id"], p + ".id"), _text(e.get("path"), p + ".path", optional=True),
                _text(e.get("content", ""), p + ".content", empty=True), e.get("kind", "source"),
                _text(e.get("tool_ref"), p + ".tool_ref", optional=True),
                _text(e.get("owner"), p + ".owner", optional=True),
                _text(e.get("claim"), p + ".claim", optional=True), e.get("polarity", "support"),
                e.get("verified"), _strings(e.get("contradicts", []), p + ".contradicts")))
        history = []
        for i, item in enumerate(_sequence(row.get("history", []), "history")):
            p = f"history[{i}]"
            h = allowed_object(item, {"id", "task_id", "trial_id", "context", "action",
                "object", "candidate", "evidence_ref", "verifier", "resource"}, {"id"}, p)
            if h.get("task_id", task) != task or h.get("trial_id", trial) != trial:
                raise BoundaryError(p + ": history belongs to a different task or trial")
            verifier = None
            if h.get("verifier") is not None:
                v = allowed_object(h["verifier"], {"status", "evidence_refs", "tool_ref", "detail"},
                                   {"status"}, p + ".verifier")
                if v["status"] not in ("pass", "fail", "unknown"):
                    raise BoundaryError(p + ".verifier.status: invalid status")
                verifier = Verifier(v["status"], _strings(v.get("evidence_refs", []), p + ".verifier.evidence_refs"),
                    _text(v.get("tool_ref"), p + ".verifier.tool_ref", optional=True),
                    _text(v.get("detail", ""), p + ".verifier.detail", empty=True))
            resource = None
            if h.get("resource") is not None:
                r = allowed_object(h["resource"], {"tokens", "calls", "elapsed_ms"}, set(), p + ".resource")
                resource = Resource(**{key: _number(val, p + ".resource." + key, nonnegative=True)
                                       for key, val in r.items()})
            refs = h.get("evidence_ref", [])
            refs = [refs] if isinstance(refs, str) else refs
            history.append(TraceEvent(_text(h["id"], p + ".id"), task, trial,
                *(_text(h.get(key), p + "." + key, optional=True, empty=key == "context")
                  for key in ("context", "action", "object", "candidate")),
                _strings(refs, p + ".evidence_ref"), verifier, resource))
        for label, identifiers in (("candidate paths", [c.path for c in candidates]),
                                   ("evidence ids", [e.id for e in evidence]),
                                   ("history ids", [h.id for h in history])):
            if len(identifiers) != len(set(identifiers)):
                raise BoundaryError(f"duplicate {label}")
        model = allowed_object(row.get("model_config", {}),
            {"model", "provider", "reasoning_effort", "temperature", "seed", "max_tokens"}, set(), "model_config")
        for key, val in model.items():
            if key in {"model", "provider", "reasoning_effort"}:
                _text(val, "model_config." + key)
            else:
                _number(val, "model_config." + key, nonnegative=True)
                if key in {"seed", "max_tokens"} and not isinstance(val, int):
                    raise BoundaryError("model_config." + key + ": expected integer")
        inventory = row.get("repository_files")
        return cls(task, trial, _text(row.get("issue", ""), "issue", empty=True),
            _text(row.get("context", ""), "context", empty=True), tuple(candidates), tuple(evidence),
            tuple(history), None if inventory is None else _strings(inventory, "repository_files"),
            tuple(sorted(model.items())))

    def digest(self) -> str:
        return digest(asdict(self))

    def as_dict(self) -> dict:
        result = json.loads(json.dumps(asdict(self), ensure_ascii=False, allow_nan=False))
        result["model_config"] = dict(self.model_config)
        for event in result["history"]:
            if event["resource"] is not None:
                event["resource"] = {k: v for k, v in event["resource"].items() if v is not None}
        return result

    def to_dict(self) -> dict:
        return self.as_dict()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Assessment:
    candidate: str
    verdict: str
    score: float
    reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()
    tool_refs: tuple[str, ...] = ()
    event_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModuleProvenance:
    implementation: str
    snapshot_digest: str
    parameters_digest: str
    source_fields: tuple[str, ...]


@dataclass(frozen=True)
class ModuleOutput:
    module: str
    assessments: tuple[Assessment, ...]
    vote: str | None
    abstain: bool
    provenance: ModuleProvenance

    def as_dict(self) -> dict:
        # JSON roundtrip converts tuples to arrays, preserving an exact JSON API.
        return json.loads(json.dumps(asdict(self), ensure_ascii=False, allow_nan=False))
