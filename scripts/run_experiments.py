#!/usr/bin/env python3
"""Plan registered experiments by default; execute only with an explicit adapter."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from audit_framework.experiments.adapters import import_symbol
from audit_framework.experiments.catalog import CONFIG_ROOT, load_registry
from audit_framework.experiments.contracts import output_path, require
from audit_framework.experiments.planning import build_plan
from audit_framework.experiments.runner import execute_plan, load_runtime_inputs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', help='List registered experiments without executing')
    parser.add_argument('--experiment', default='all')
    parser.add_argument('--data-root', type=Path, default=ROOT / 'data')
    parser.add_argument('--config-root', type=Path, default=CONFIG_ROOT)
    parser.add_argument('--out', type=Path, default=ROOT / 'runs' / 'experiment_plan.json')
    parser.add_argument('--limit-units', type=int, help='Select whole assignment grids, never partial pairs')
    parser.add_argument('--parameters', type=Path, help='JSON object overriding explicit execution limits')
    parser.add_argument('--execute', action='store_true', help='Explicitly invoke the selected execution adapter')
    parser.add_argument('--snapshots', type=Path, help='Outcome-free runtime envelope JSONL; required for execution')
    parser.add_argument('--adapter', default='audit_framework.experiments.adapters:core_adapter')
    parser.add_argument('--provider-config', type=Path, help='Adapter-specific JSON configuration; no API keys in files')
    args = parser.parse_args(argv)
    try:
        if args.list:
            registry = load_registry(args.config_root)
            print(json.dumps({name: {'conditions': [c['id'] for c in entry['conditions']],
                                    'cohorts': entry['cohorts'], 'endpoint': entry['endpoint']}
                              for name, entry in registry['experiments'].items()}, indent=2))
            return 0
        parameters = json.loads(args.parameters.read_text(encoding='utf-8')) if args.parameters else None
        plan = build_plan(args.experiment, data_root=args.data_root, config_root=args.config_root,
                          limit_units=args.limit_units, parameters=parameters)
        target = output_path(args.out, ROOT)
        require(not target.exists(), f'Output already exists; choose a new --out path: {target}')
        artifact = plan
        if args.execute:
            require(args.snapshots is not None, '--execute requires --snapshots')
            adapter = import_symbol(args.adapter)
            if args.provider_config:
                require(callable(getattr(adapter, 'configure', None)), 'Adapter does not accept provider configuration')
                config = json.loads(args.provider_config.read_text(encoding='utf-8'))
                adapter = adapter.configure(config)
            artifact = execute_plan(plan, load_runtime_inputs(args.snapshots), evaluate=adapter, execute=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents concurrent runs from overwriting one another.
        with target.open('x', encoding='utf-8', newline='\n') as handle:
            json.dump(artifact, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write('\n')
        print(json.dumps({'mode': artifact['mode'], 'output': str(target), 'plan_sha256': plan['plan_sha256'],
                          'summary': plan['summary'], 'scheduled_n': len(plan['jobs']),
                          'completed_n': artifact.get('completed_n'),
                          'noncompleted_n': artifact.get('noncompleted_n')}, indent=2))
        return 0 if artifact.get('noncompleted_n', 0) == 0 else 2
    except (ValueError, OSError, ImportError, AttributeError, KeyError) as error:
        print(f'Experiment protocol error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
