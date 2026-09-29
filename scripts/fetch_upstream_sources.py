#!/usr/bin/env python3
"""Acquire a bounded, pinned source selection; default operation is offline verification."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'third_party'
LOCK = VENDOR / 'sources.lock.json'
MAX_FILE_BYTES = 2 * 1024 * 1024
SOURCES = {
    'swe_agent': {
        'repository': 'SWE-agent/SWE-agent',
        'commit': '3ea751c087f32b16e039a2233dd6eefecef325d5',
        'license': 'MIT', 'license_file': 'LICENSE', 'paper_references': [2],
        'files': ['LICENSE', 'sweagent/types.py', 'sweagent/run/run_single.py',
                  'sweagent/run/run_batch.py', 'sweagent/run/batch_instances.py',
                  'sweagent/run/merge_predictions.py', 'sweagent/run/common.py',
                  'sweagent/agent/hooks/abstract.py', 'config/default.yaml'],
    },
    'mini_swe_agent': {
        'repository': 'SWE-agent/mini-swe-agent',
        'commit': '04d809ceab9df28f9adaed044884180159172930',
        'license': 'MIT', 'license_file': 'LICENSE.md', 'paper_references': [9],
        'files': ['LICENSE.md', 'src/minisweagent/agents/default.py',
                  'src/minisweagent/utils/serialize.py'],
    },
    'swe_bench_pro': {
        'repository': 'scaleapi/SWE-bench_Pro-os',
        'commit': '66f92766bba642462d4bbe5479e83f91f9211862',
        'license': 'MIT', 'license_file': 'LICENSE', 'paper_references': [6, 7],
        'files': ['LICENSE', 'helper_code/gather_patches.py',
                  'helper_code/image_uri.py', 'swe_bench_pro_eval.py', 'requirements.txt'],
    },
    'critic': {
        'repository': 'microsoft/ProphetNet',
        'commit': '5cf70eb41cdaa1d8faa3e1265d95ee5792d49a53',
        'license': 'MIT', 'license_file': 'LICENSE', 'paper_references': [30],
        'files': ['LICENSE', 'CRITIC/src/qa/critic.py', 'CRITIC/src/program/critic.py',
                  'CRITIC/src/utils.py'],
    },
}


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def target_path(source: str, upstream_path: str) -> Path:
    p = PurePosixPath(upstream_path)
    if p.is_absolute() or '..' in p.parts or '\\' in upstream_path:
        raise ValueError('Invalid upstream path')
    target = (VENDOR / source / Path(*p.parts)).resolve()
    if not target.is_relative_to(VENDOR.resolve()):
        raise ValueError('Source destination leaves third_party')
    return target


def source_url(spec: dict, path: str) -> str:
    if not re.fullmatch(r'[0-9a-f]{40}', spec['commit']):
        raise ValueError('Source must use a full commit ID')
    return f"https://raw.githubusercontent.com/{spec['repository']}/{spec['commit']}/{path}"


def download(url: str) -> bytes:
    for attempt in range(3):
        try:
            request_url = url if attempt == 0 else url + ('?download=1' if attempt == 1 else '?raw=true')
            request = urllib.request.Request(request_url, headers={'User-Agent': 'audit-framework-source-fetcher/1'})
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.read(MAX_FILE_BYTES + 1)
        except (urllib.error.URLError, TimeoutError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code not in (429, 500, 502, 503, 504):
                raise
            if attempt == 2:
                raise RuntimeError(f'Download failed: {url}: {exc}') from exc
            time.sleep(attempt + 1)


def verify_sources() -> dict:
    lock = json.loads(LOCK.read_text(encoding='utf-8'))
    if lock['schema'] != 'audit-upstream-sources/v1':
        raise ValueError('Unknown source manifest schema')
    if set(lock['sources']) != set(SOURCES):
        raise ValueError('Manifest source set differs from pinned selection')
    total = 0
    count = 0
    for name, spec in SOURCES.items():
        row = lock['sources'][name]
        for key in ('repository', 'commit', 'license', 'license_file', 'paper_references'):
            if row[key] != spec[key]:
                raise ValueError(f'{name}: manifest {key} differs')
        if set(row['files']) != set(spec['files']):
            raise ValueError(f'{name}: manifest file set differs')
        for path, expected in row['files'].items():
            data = target_path(name, path).read_bytes()
            if expected['url'] != source_url(spec, path):
                raise ValueError(f'{name}/{path}: source URL differs')
            if file_hash(data) != expected['sha256'] or len(data) != expected['bytes']:
                raise ValueError(f'{name}/{path}: source hash differs')
            count += 1
            total += len(data)
        license_data = target_path(name, spec['license_file']).read_text(encoding='utf-8')
        if 'Permission is hereby granted' not in license_data or 'Copyright' not in license_data:
            raise ValueError(f'{name}: incomplete MIT attribution')
    return {'sources': len(SOURCES), 'files': count, 'bytes': total, 'verified': True}


def fetch_sources() -> dict:
    """Fetch only public raw files; never clone, install, or run upstream code."""
    previous = json.loads(LOCK.read_text(encoding='utf-8')) if LOCK.exists() else None
    manifest = {'schema': 'audit-upstream-sources/v1', 'sources': {}}
    staged = []
    for name, spec in SOURCES.items():
        row = {k: v for k, v in spec.items() if k != 'files'}
        row['files'] = {}
        for path in spec['files']:
            url = source_url(spec, path)
            print(f'Fetch {name}/{path}', flush=True)
            data = download(url)
            if len(data) > MAX_FILE_BYTES:
                raise ValueError('Source exceeds per-file acquisition bound')
            entry = {'url': url, 'sha256': file_hash(data), 'bytes': len(data)}
            if previous is not None:
                old = previous['sources'][name]['files'][path]
                if old != entry:
                    raise ValueError(f'{name}/{path}: downloaded bytes differ from lock')
            target = target_path(name, path)
            if target.exists() and target.read_bytes() != data:
                raise ValueError(f'{name}/{path}: refusing to replace modified local source')
            row['files'][path] = entry
            staged.append((target, data))
        manifest['sources'][name] = row
    if sum(len(data) for _, data in staged) > 25 * 1024 * 1024:
        raise ValueError('Source selection exceeds total acquisition bound')
    # Every response is checked before publishing the selected source set.
    for target, data in staged:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
    if previous is None:
        LOCK.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return verify_sources()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true', help='Download the pinned allowlist (network opt-in)')
    parser.add_argument('--verify', action='store_true', help='Verify local source hashes offline (default)')
    args = parser.parse_args()
    if args.fetch and args.verify:
        parser.error('Choose --fetch or --verify')
    result = fetch_sources() if args.fetch else verify_sources()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
