"""Offline SHA-256, filename, and credential checks for this release."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {'.git', '.venv', 'venv', '__pycache__', 'outputs', 'runs', 'downloads', 'acquired_logs', 'reproduced', 'data', 'results', 'paper', 'Picture'}
TEXT_SUFFIXES = {'.py', '.json', '.jsonl', '.csv', '.md', '.txt', '.yaml', '.yml', '.toml', '.example', '.sh'}

def verify(root: Path) -> dict:
    root = root.resolve()
    manifest = json.loads((root/'artifact_manifest.json').read_text(encoding='utf-8'))
    problems = []
    files = manifest['files']
    if manifest.get('distribution') == 'complete_code_only':
        for entry in files:
            if Path(entry['path']).parts[0] in {'data','results','paper','Picture'}:
                problems.append({'file':entry['path'],'problem':'empirical data must not be bundled'})
    seen = set()
    for entry in files:
        relative = entry['path']
        path = (root / relative).resolve()
        if relative in seen or not path.is_relative_to(root):
            problems.append({'file': relative, 'problem': 'invalid or duplicate manifest path'})
            continue
        seen.add(relative)
        if not path.is_file():
            problems.append({'file': relative, 'problem': 'missing'})
        elif path.stat().st_size != entry.get('bytes',path.stat().st_size) or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            problems.append({'file': relative, 'problem': 'SHA-256 mismatch'})
    patterns = [re.compile(r'\bsk-[A-Za-z0-9_-]{20,}\b'),
                re.compile(r'\bgh[pousr]_[A-Za-z0-9]{30,}\b'),
                re.compile(r'\bgithub_pat_[A-Za-z0-9_]{30,}\b'),
                re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')]
    for path in root.rglob('*'):
        if not path.is_file() or any(part in IGNORED or part.endswith('.egg-info') for part in path.relative_to(root).parts):
            continue
        relative = path.relative_to(root).as_posix()
        if path.suffix == '.py' and not relative.startswith('third_party/'):
            if not re.fullmatch(r'[a-z_][a-z0-9_]*\.py', path.name) or re.search(r'shenji|work1|work2|m3', path.name, re.I):
                problems.append({'file': relative, 'problem': 'nonstandard project Python filename'})
        if path.name == '.env' or path.suffix in {'.pem', '.key'}:
            problems.append({'file': relative, 'problem': 'credential file must not be distributed'})
        if path.suffix in TEXT_SUFFIXES:
            content = path.read_text(encoding='utf-8-sig', errors='replace')
            if any(pattern.search(content) for pattern in patterns):
                problems.append({'file': relative, 'problem': 'possible credential; content suppressed'})
    return {'status': 'PASS' if not problems else 'FAIL', 'files_verified': len(files), 'problems': problems}

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args(argv)
    result = verify(args.root)
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'PASS' else 1

if __name__ == '__main__':
    raise SystemExit(main())
