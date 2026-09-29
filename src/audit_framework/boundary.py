"""Strict model-facing input boundary; no evaluator records are projected silently.

Every object is validated against its local allowlist in schema.py. This first
pass additionally rejects evaluator keys anywhere, including JSON encoded in
text fields. Arbitrary natural-language secrets cannot be identified by a key
allowlist: callers must supply genuinely agent-visible source text. No data is
read from disk, environment variables, providers, or empirical result tables.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any


class BoundaryError(ValueError):
    """An input violates the agent-visible schema or information boundary."""


_FORBIDDEN = frozenset({
    "gold", "patch", "patchdiff", "testpatch", "targetpatch",
    "groundtruth", "expectedfile", "expectedfiles", "success",
    "resolved", "resolution", "repairoutcome", "outcome",
    "outcomesuccess", "firsthit", "firsthitrank", "filehit",
})


def check_boundary(value: Any, path: str = "snapshot") -> None:
    """Reject non-JSON data, nonfinite numbers and nested evaluator fields."""
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise BoundaryError(f"{path}: object keys must be strings")
            normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
            if (normalized in _FORBIDDEN or normalized.startswith("gold")
                    or normalized.startswith("filehit") or "posthoc" in normalized):
                raise BoundaryError(f"{path}.{key}: evaluator-only field")
            check_boundary(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            check_boundary(item, f"{path}[{index}]")
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                embedded = json.loads(stripped)
            except (ValueError, RecursionError):
                return
            check_boundary(embedded, f"{path}<json>")
    elif value is None or isinstance(value, (bool, int)):
        return
    elif isinstance(value, float) and math.isfinite(value):
        return
    else:
        raise BoundaryError(f"{path}: expected finite JSON data")


def allowed_object(value: Any, allowed: set[str], required: set[str], path: str) -> dict:
    if not isinstance(value, dict):
        raise BoundaryError(f"{path}: expected object")
    extra, missing = set(value) - allowed, required - set(value)
    if extra or missing:
        raise BoundaryError(f"{path}: unknown={sorted(extra)}, missing={sorted(missing)}")
    return value
