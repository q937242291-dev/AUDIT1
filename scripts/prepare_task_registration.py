"""Prepare external identity-only registrations; fetching requires explicit --fetch."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from audit_framework.experiments.benchmarks import BENCHMARKS,fetch_catalog,identity_catalog,read_catalog
from audit_framework.experiments.cohorts import cohort_from_catalog,seal_registration

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--links',action='store_true')
 p.add_argument('--benchmark',choices=BENCHMARKS,default='pro_python_266')
 p.add_argument('--cohort',default='localization_methods');p.add_argument('--revision')
 group=p.add_mutually_exclusive_group();group.add_argument('--fetch',action='store_true');group.add_argument('--rows-jsonl',type=Path);group.add_argument('--catalog',type=Path);group.add_argument('--units-json',type=Path)
 p.add_argument('--task-ids',type=Path);p.add_argument('--selection',type=Path);p.add_argument('--out',type=Path)
 a=p.parse_args(argv)
 if a.links:
  print(json.dumps(BENCHMARKS,ensure_ascii=False,indent=2));return 0
 if not a.out:p.error('--out must name an external registration directory')
 if a.units_json:
  reg=seal_registration(a.cohort,json.loads(a.units_json.read_text()),source=str(a.units_json.resolve()))
  catalog=None
 else:
  if a.fetch:catalog=fetch_catalog(a.benchmark,revision=a.revision)
  elif a.rows_jsonl:catalog=identity_catalog([json.loads(line) for line in a.rows_jsonl.read_text(encoding='utf-8-sig').splitlines() if line.strip()],a.benchmark,revision=a.revision)
  elif a.catalog:catalog=read_catalog(a.catalog)
  else:p.error('Choose --fetch, --rows-jsonl, --catalog or --units-json; no task IDs are fabricated')
  reg=cohort_from_catalog(a.cohort,catalog,task_ids=json.loads(a.task_ids.read_text()) if a.task_ids else None,selection=json.loads(a.selection.read_text()) if a.selection else None)
 a.out.mkdir(parents=True,exist_ok=True)
 outputs={a.cohort+'.json':reg}
 if catalog:outputs['benchmark_catalog.json']=catalog
 for name in outputs:
  if (a.out/name).exists():p.error('Refusing to overwrite existing registration: '+str(a.out/name))
 for name,value in outputs.items():(a.out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print('Registration created without evaluator fields.');return 0
if __name__=='__main__':raise SystemExit(main())
