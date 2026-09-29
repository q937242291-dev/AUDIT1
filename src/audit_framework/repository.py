"""Read-only repository evidence tools. No shell, patch application or model calls."""
from __future__ import annotations
import hashlib
from pathlib import Path, PurePosixPath

EXCLUDED = {'.git', '.hg', '.svn', '.venv', 'venv', '__pycache__', 'node_modules'}

def repository_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise ValueError('Use a nonempty repository-relative POSIX path')
    parts = PurePosixPath(relative).parts
    if relative.startswith('/') or ':' in relative or '..' in parts or any(x in EXCLUDED for x in parts):
        raise ValueError('Path is outside the permitted repository source')
    if any(x.startswith('.env') or x.lower().endswith(('.pem', '.key')) for x in parts):
        raise ValueError('Credential files are not repository evidence')
    root = root.resolve(strict=True)
    path = root.joinpath(*parts)
    if not path.resolve().is_relative_to(root):
        raise ValueError('Resolved path escapes repository')
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError('Symbolic links are not followed by this evidence reader')
    return path

def inventory(root: Path) -> list[str]:
    root = root.resolve(strict=True)
    paths = []
    # Prune excluded directories before descent; never traverse symlink directories.
    import os
    for folder, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(d for d in directories if d not in EXCLUDED and not Path(folder, d).is_symlink())
        for name in sorted(files):
            relative = Path(folder, name).relative_to(root).as_posix()
            try:
                path = repository_path(root, relative)
            except ValueError:
                continue
            if path.is_file():
                paths.append(relative)
    return sorted(paths)

def read_file(root: Path, relative: str, max_chars: int = 8000) -> dict:
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError('max_chars must be a positive integer')
    path = repository_path(root, relative)
    with path.open('r', encoding='utf-8') as handle:
        content = handle.read(max_chars + 1)
    if '\x00' in content:
        raise ValueError('Binary data is not source-text evidence')
    truncated = len(content) > max_chars
    content = content[:max_chars]
    return {'path': relative, 'content': content, 'truncated': truncated,
            'content_sha256': hashlib.sha256(content.encode('utf-8')).hexdigest()}

def search(root: Path, query: str, *, limit: int = 20, max_chars: int = 8000) -> list[dict]:
    if not query or type(limit) is not int or limit < 1:
        raise ValueError('A nonempty literal query and positive limit are required')
    matches = []
    for path in inventory(root):
        try:
            source = read_file(root, path, max_chars)
        except (OSError, ValueError, UnicodeError):
            continue
        for number, line in enumerate(source['content'].splitlines(), 1):
            if query in line:
                matches.append({'path': path, 'line': number, 'text': line})
                if len(matches) == limit:
                    return matches
    return matches

def make_snapshot(root: Path, task_id: str, issue: str, paths: list[str], *, trial_id: str = 'default', max_chars: int = 8000) -> dict:
    """Inspect proposed files; file readability is evidence, not repair correctness."""
    from .schema import Snapshot
    if len(paths) != len(set(paths)):
        raise ValueError('Candidate paths must be unique')
    snapshot = {'task_id': task_id, 'trial_id': trial_id, 'issue': issue,
                'candidates': [], 'evidence': [], 'history': [],
                'repository_files': inventory(root), 'model_config': {}}
    for index, path in enumerate(paths):
        ref, tool_ref = f'source_{index + 1}', f'read_file_{index + 1}'
        source = read_file(root, path, max_chars)
        snapshot['candidates'].append({'path': path, 'evidence_refs': [ref]})
        snapshot['evidence'].append({'id': ref, 'path': path, 'owner': path,
            'content': source['content'], 'kind': 'source', 'tool_ref': tool_ref})
        snapshot['history'].append({'id': tool_ref, 'task_id': task_id,
            'trial_id': trial_id, 'action': 'read_file', 'object': path,
            'candidate': path, 'evidence_ref': [ref]})
    Snapshot.from_dict(snapshot)
    return snapshot

