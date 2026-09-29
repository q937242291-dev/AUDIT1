"""Offline analysis of released data; never launches agent experiments."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'outputs' / 'analysis')
    parser.add_argument('--figures', action='store_true')
    parser.add_argument('--tests', action='store_true', help='Run fixture-based code tests before analysis')
    parser.add_argument('--tests-only', action='store_true', help='Test code without processing empirical data')
    args = parser.parse_args(argv)
    out = args.out.resolve()
    for protected in (ROOT / 'data', ROOT / 'results', ROOT / 'paper', ROOT / 'src'):
        if out == protected or protected in out.parents or out in protected.parents:
            parser.error('Choose a separate output directory, outside the released data/code/results.')
    env = dict(os.environ)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONUTF8'] = '1'
    env['PYTHONPATH'] = str(ROOT / 'src')
    stages = []
    def run(label, command):
        result = subprocess.run([sys.executable, '-B', *map(str, command)], cwd=ROOT, env=env)
        stages.append({'stage': label, 'returncode': result.returncode})
        if result.returncode:
            raise SystemExit(result.returncode)
    if args.tests or args.tests_only:
        run('unit_contract_tests', ['-m', 'unittest', 'discover', '-s', ROOT/'tests', '-p', 'test_*.py', '-v'])
    if args.tests_only:
        return 0
    for script, folder in [
        ('reproduce_controlled_experiments.py', 'controlled'),
        ('reproduce_success_trajectories.py', 'observational'),
        ('reproduce_model_swap.py', 'model_swap'),
        ('reproduce_repair_endpoints.py', 'repair'),
    ]:
        command = [ROOT/'scripts'/script, '--out', out/folder]
        if folder != 'repair':
            command += ['--root', ROOT]
        run(folder, command)
    tables = out/'paper_tables'
    tables.mkdir(parents=True, exist_ok=True)
    for path in sorted((out/'controlled').glob('table_*.csv')):
        shutil.copyfile(path, tables/path.name)
    for panel in 'abc':
        shutil.copyfile(out/f'observational/table3_panel_{panel}.csv', tables/f'table_03_panel_{panel}.csv')
    shutil.copyfile(out/'repair/component_activity.csv', tables/'table_01_activation_and_necessity.csv')
    shutil.copyfile(out/'model_swap/table_10_model_swap.csv', tables/'table_10_model_swap.csv')
    if args.figures:
        run('figures', [ROOT/'scripts/generate_figures.py', '--root', ROOT, '--results', out, '--out', out/'figures'])
    report = {'status': 'complete', 'stages': stages, 'provider_calls': 0, 'benchmark_reruns': 0,
              'input_directory': 'data', 'output_directory': str(out),
              'analysis': 'Released row-level measurements; missing measurements remain missing.'}
    (out/'analysis_report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print('Offline analysis complete. No model calls or benchmark reruns.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

