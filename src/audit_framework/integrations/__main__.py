"""Offline CLI: normalize traces, audit a prefix, or print pinned SWE-agent arguments."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import build_swe_agent_invocation, parse_trajectory, snapshot_from_trajectory


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('parse', 'audit-prefix'):
        command = sub.add_parser(name)
        command.add_argument('--trajectory', required=True, type=Path)
        command.add_argument('--source', required=True, choices=['swe_agent', 'swe_bench_pro', 'mini_swe_agent', 'deepswe'])
        command.add_argument('--task-id', required=True)
        command.add_argument('--trial-id', default='default')
        if name == 'audit-prefix':
            command.add_argument('--before-index', required=True, type=int)
            command.add_argument('--context', required=True, type=Path,
                                 help='JSON with candidates and optional issue/repository_files/model_config')
    plan = sub.add_parser('swe-agent-plan')
    for flag in ('config', 'repository', 'issue-file', 'output-dir', 'model'):
        plan.add_argument('--' + flag, required=True)
    plan.add_argument('--cost-limit', required=True, type=float)
    args = parser.parse_args(argv)
    if args.command == 'swe-agent-plan':
        result = build_swe_agent_invocation(**{k: v for k, v in vars(args).items() if k != 'command'}).as_dict()
    else:
        raw = json.loads(args.trajectory.read_text(encoding='utf-8'))
        trace = parse_trajectory(raw, source=args.source, task_id=args.task_id, trial_id=args.trial_id)
        if args.command == 'parse':
            result = trace.as_dict()
        else:
            context = json.loads(args.context.read_text(encoding='utf-8'))
            if not isinstance(context, dict) or set(context) - {'candidates', 'issue', 'repository_files', 'model_config'}:
                raise ValueError('Context must contain only agent-visible candidate inputs')
            if 'candidates' not in context:
                raise ValueError('Context requires an explicit candidate list')
            snapshot = snapshot_from_trajectory(trace, before_index=args.before_index, **context)
            from ..engine import evaluate_conditions
            result = evaluate_conditions(snapshot)
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
