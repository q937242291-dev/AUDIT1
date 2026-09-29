"""Read and import only the selected, SHA-256 verified upstream files."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
THIRD_PARTY = ROOT / 'third_party'


def source_manifest() -> dict:
    return json.loads((THIRD_PARTY / 'sources.lock.json').read_text(encoding='utf-8'))


def source_info(name: str) -> dict:
    return source_manifest()['sources'][name]


def verified_path(name: str, path: str) -> Path:
    spec = source_info(name)
    expected = spec['files'][path]
    root = (THIRD_PARTY / name).resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise ValueError('Source path leaves its vendor directory')
    data = target.read_bytes()
    if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
        raise ValueError(f'Upstream source integrity failure: {name}/{path}')
    return target


def load_pure_module(name: str, path: str):
    # Original modules with only stdlib imports and no entry-point side effects.
    allowed = {('mini_swe_agent', 'src/minisweagent/utils/serialize.py'),
               ('swe_bench_pro', 'helper_code/gather_patches.py')}
    if (name, path) not in allowed:
        raise ValueError('This upstream module is not approved for offline import')
    file = verified_path(name, path)
    spec = importlib.util.spec_from_file_location(f'_audit_vendor_{name}', file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def merge_mini_metadata(*dictionaries: dict | None) -> dict:
    """Call mini-swe-agent's original recursive_merge implementation."""
    return load_pure_module('mini_swe_agent', 'src/minisweagent/utils/serialize.py').recursive_merge(*dictionaries)
