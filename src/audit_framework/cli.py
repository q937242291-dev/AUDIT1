"""AUDIT command line: fixed snapshots, module removals, and offline evaluation."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write_json(value, path):
    text = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
    if path is None:
        print(text, end='')
        return
    path = Path(path).resolve()
    root = Path(__file__).resolve().parents[2]
    for protected in ('data', 'results', 'paper', 'src', 'configs', 'third_party'):
        if path.is_relative_to(root / protected):
            raise ValueError('Outputs cannot overwrite released data, sources, or configurations')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        handle.write(text)

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('conditions', help='List the nine registered configurations')
    for name in ('evaluate', 'ablate', 'validate'):
        sub = commands.add_parser(name)
        sub.add_argument('--snapshot', required=True, type=Path)
        sub.add_argument('--out', type=Path)
        if name == 'evaluate':
            sub.add_argument('--condition', default='full_audit')
    inspect = commands.add_parser('inspect', help='Create evidence from a read-only repository checkout')
    inspect.add_argument('--repository', type=Path, required=True)
    inspect.add_argument('--task-id', required=True)
    inspect.add_argument('--trial-id', default='default')
    inspect.add_argument('--issue-file', type=Path, required=True)
    inspect.add_argument('--candidate', action='append', required=True, help='Repository-relative source path; repeat as needed')
    inspect.add_argument('--max-chars', type=int, default=8000)
    inspect.add_argument('--out', type=Path)
    score = commands.add_parser('score', help='Evaluator-only localization scoring, not model input')
    score.add_argument('--ranking', type=Path, required=True, help='JSON list of ranked repository paths')
    score.add_argument('--gold-files', type=Path, required=True, help='JSON list of evaluator-only reference paths')
    score.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    try:
        from .conditions import available_conditions, load_condition
        from .schema import Snapshot
        if args.command == 'conditions':
            result = [load_condition(name).as_dict() for name in available_conditions()]
        elif args.command == 'inspect':
            from .repository import make_snapshot
            result = make_snapshot(args.repository, args.task_id, args.issue_file.read_text(encoding='utf-8'),
                args.candidate, trial_id=args.trial_id, max_chars=args.max_chars)
        elif args.command == 'score':
            from .evaluation import localization
            result = localization(read_json(args.ranking), read_json(args.gold_files))
        else:
            raw = read_json(args.snapshot)
            snapshot = Snapshot.from_dict(raw)
            if args.command == 'validate':
                result = {'status': 'valid', 'task_id': snapshot.task_id, 'snapshot_digest': snapshot.digest()}
            else:
                from .engine import evaluate
                if args.command == 'evaluate':
                    result = evaluate(raw, args.condition)
                else:
                    from .engine import evaluate_conditions
                    # Compute once, then remove only the registered controller input.
                    rows = list(evaluate_conditions(raw).values())
                    result = {'task_id': snapshot.task_id, 'snapshot_digest': snapshot.digest(), 'conditions': rows}
        write_json(result, getattr(args, 'out', None))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f'AUDIT: {exc}\n')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
