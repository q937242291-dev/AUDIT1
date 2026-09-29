"""Explicit evaluator-side preparation for the pinned official SWE-bench Pro harness."""
from __future__ import annotations

import json
from functools import partial
from pathlib import Path

from .upstream import load_pure_module, source_info, verified_path


def gather_pro_predictions(directory: str | Path, *, model_name: str) -> list[dict]:
    """Call the original Scale helper after rejecting ambiguous/malformed prediction files."""
    root = Path(directory)
    if not root.is_dir() or not model_name.strip():
        raise ValueError('Prediction directory and model_name are required')
    folders = sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith('instance_'))
    ids = set()
    for folder in folders:
        candidates = list(folder.glob('*.pred'))
        if len(candidates) != 1:
            raise ValueError(f'Expected exactly one prediction in {folder.name}')
        text = candidates[0].read_text(encoding='utf-8')
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            if text.lstrip().startswith(('{', '[')):
                raise ValueError('Malformed JSON prediction')
            row = {'instance_id': folder.name, 'model_patch': text}
        if not isinstance(row, dict):
            raise ValueError('Prediction JSON must be an object')
        instance = row.get('instance_id', folder.name)
        patch = row.get('model_patch', row.get('patch'))
        if not isinstance(instance, str) or not instance or instance in ids or not isinstance(patch, str):
            raise ValueError('Prediction requires unique instance_id and a string patch')
        ids.add(instance)
    helper = load_pure_module('swe_bench_pro', 'helper_code/gather_patches.py')
    # Upstream uses locale-dependent open(). Supply UTF-8 at its I/O boundary
    # while preserving the original source and gather algorithm byte-for-byte.
    helper.open = partial(open, encoding='utf-8')
    rows = helper.gather_patches_from_local(str(root), model_name)
    if len(rows) != len(folders) or {r['instance_id'] for r in rows} != ids:
        raise ValueError('Upstream gatherer omitted or changed a prediction')
    return rows


def build_pro_evaluation_invocation(*, raw_sample_path: str | Path, patch_path: str | Path,
        scripts_dir: str | Path, output_dir: str | Path, dockerhub_username: str,
        num_workers: int = 1, python: str = 'python') -> dict:
    """Return argv for official v1 grading. Does not run Docker, Modal or evaluation."""
    if type(num_workers) is not int or num_workers < 1:
        raise ValueError('num_workers must be a positive integer')
    if not dockerhub_username or dockerhub_username.startswith('-'):
        raise ValueError('Explicit public image namespace required')
    if not Path(raw_sample_path).is_file() or not Path(patch_path).is_file() or not Path(scripts_dir).is_dir():
        raise ValueError('Task metadata, prediction file and official run_scripts must exist')
    source = source_info('swe_bench_pro')
    entry = verified_path('swe_bench_pro', 'swe_bench_pro_eval.py')
    argv = [python, str(entry), '--raw_sample_path', str(raw_sample_path), '--patch_path', str(patch_path),
            '--output_dir', str(output_dir), '--scripts_dir', str(scripts_dir),
            '--dockerhub_username', dockerhub_username, '--num_workers', str(num_workers),
            '--use_local_docker', '--block_network']
    return {'repository': source['repository'], 'commit': source['commit'],
            'protocol': 'SWE-bench-Pro-v1', 'argv': argv, 'executed': False}
