"""Provider-independent contracts shared by planning, execution and scoring."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

MODULES = ("grounding", "ownership", "contradiction", "detour",
           "path_verification", "memory", "abstention")
RUNTIME_FIELDS = frozenset({
    "task_id", "trial_id", "issue", "context", "candidates", "evidence",
    "history", "repository_files", "model_config",
})
FORBIDDEN = frozenset({
    "gold", "gold_patch", "patch", "test_patch", "gold_files",
    "gold_target_files", "target_files", "target_paths", "expected_output",
    "evaluator", "evaluator_labels", "labels", "outcome", "outcomes",
    "resolved", "repair_outcome", "future_payload", "future_patch",
    "future_tests", "future_test_pass_ratio", "fail_to_pass", "pass_to_pass",
    "location_payload", "diff_payload", "tests_status",
})


class ProtocolError(ValueError):
    """A manifest, boundary, completion or execution contract was violated."""


def require(value: Any, message: str) -> None:
    if not value:
        raise ProtocolError(message)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def reject_outcomes(value: Any, location: str = "snapshot") -> None:
    """Reject evaluator fields recursively, including nested tool/provider inputs."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key).lower().replace("-", "_")
            forbidden = (name in FORBIDDEN or name.startswith("gold_") or
                         "posthoc" in name or "filehit" in name or
                         name.startswith(("file_hit", "hit@", "hunkhit")))
            require(not forbidden, f"Evaluator-only field at {location}.{key}")
            reject_outcomes(child, f"{location}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            reject_outcomes(child, f"{location}[{index}]")


def runtime_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    """Accept only an explicitly constructed, outcome-free runtime snapshot."""
    require(isinstance(value, Mapping), "Runtime snapshot must be a mapping")
    reject_outcomes(value)
    require(not set(value) - RUNTIME_FIELDS,
            f"Unregistered runtime fields: {sorted(set(value) - RUNTIME_FIELDS)}")
    from ..schema import Snapshot
    Snapshot.from_dict(dict(value))
    return deepcopy(dict(value))


def condition_modules(condition: Mapping[str, Any]) -> tuple[str, ...]:
    enabled = tuple(condition.get("enabled_modules", MODULES))
    require(len(enabled) == len(set(enabled)) and not set(enabled) - set(MODULES),
            "Unknown or duplicate audit module")
    return tuple(name for name in MODULES if name in enabled)


def validate_component_grid(conditions: Sequence[Mapping[str, Any]]) -> None:
    require(len(conditions) == 9, "Component grid must contain nine configurations")
    by_id = {c["id"]: c for c in conditions}
    expected = {"full_audit", "majority_controller"} | {f"minus_{m}" for m in MODULES}
    require(set(by_id) == expected, "Component grid IDs differ from registered grid")
    full = by_id["full_audit"]
    require(condition_modules(full) == MODULES and full["controller"] == "full",
            "Full audit must enable all modules")
    for module in MODULES:
        changed = by_id[f"minus_{module}"]
        require(set(condition_modules(changed)) == set(MODULES) - {module},
                f"no_{module} is not exactly one removal")
        require(changed["controller"] == "full", "Removal changed controller")
    majority = by_id["majority_controller"]
    require(condition_modules(majority) == MODULES and majority["controller"] == "majority",
            "Majority replacement must retain every module")
    for c in conditions:
        for key in ("model_alias", "prompt_template", "pipeline", "reasoning_effort"):
            require(c.get(key) == full.get(key), f"Component grid changes fixed {key}")


PAIR_FIELDS = ("experiment", "cohort", "unit_id", "instance_id", "replicate",
               "checkpoint_id", "endpoint")
FIXED_FIELDS = ("repository_state", "base_commit", "protocol_sha256",
                "prompt_template_sha256", "solver_model", "snapshot_sha256")


def align_completed_pairs(rows: Sequence[Mapping[str, Any]], control: str, treatment: str,
                          *, fixed_fields: Sequence[str] = FIXED_FIELDS) -> dict[str, Any]:
    """Require identical scheduled keys; exclude errors only after validating alignment."""
    require(control != treatment, "Pair conditions must differ")
    groups: dict[str, dict[tuple[str, ...], Mapping[str, Any]]] = {control: {}, treatment: {}}
    for row in rows:
        condition = row.get("condition_id")
        if condition not in groups:
            continue
        require(all(k in row for k in PAIR_FIELDS), "Pair row missing identity fields")
        require(row.get("status") in {"completed", "error", "incomplete", "blocked"},
                "Pair row missing explicit execution status")
        key = tuple(str(row[k]) for k in PAIR_FIELDS)
        require(key not in groups[condition], f"Duplicate pair key: {condition} {key}")
        groups[condition][key] = row
    left, right = groups[control], groups[treatment]
    require(left and set(left) == set(right), "Scheduled pair keys differ; missing rows cannot be dropped")
    pairs, excluded = [], []
    for key in sorted(left):
        a, b = left[key], right[key]
        for field in fixed_fields:
            require(field in a and field in b and a[field] == b[field],
                    f"Pair changes fixed field {field}: {key}")
        if a["status"] == b["status"] == "completed":
            pairs.append((deepcopy(dict(a)), deepcopy(dict(b))))
        else:
            excluded.append({"key": list(key), "control_status": a["status"],
                             "treatment_status": b["status"]})
    return {"scheduled_n": len(left), "completed_pair_n": len(pairs),
            "excluded_n": len(excluded), "pairs": pairs, "excluded": excluded}


def output_path(path: Path, package_root: Path) -> Path:
    """Generated runs cannot overwrite the empirical corpus or shipped artifacts."""
    resolved = path.resolve()
    for name in ("data", "paper", "results", "src", "scripts", "tests"):
        require(not resolved.is_relative_to((package_root / name).resolve()),
                f"Run output cannot be inside {name}/")
    return resolved
