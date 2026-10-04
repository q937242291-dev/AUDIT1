"""Validate supplied measurements against the current manuscript; no provider calls."""
from __future__ import annotations
import argparse,json,os,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
STAGES={'controlled':'reproduce_controlled_experiments.py','observational':'reproduce_success_trajectories.py','model_swap':'reproduce_model_swap.py','repair':'reproduce_repair_endpoints.py','redundancy':'reproduce_redundancy.py'}

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=ROOT/'outputs/analysis');p.add_argument('--data-root',type=Path);p.add_argument('--pro-catalog',type=Path);p.add_argument('--identity-root',type=Path);p.add_argument('--task-list-root',type=Path);p.add_argument('--stages',nargs='+',choices=STAGES,default=list(STAGES));p.add_argument('--figures',action='store_true');p.add_argument('--tests',action='store_true');p.add_argument('--tests-only',action='store_true')
 a=p.parse_args(argv);env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',PYTHONPATH=str(ROOT/'src'))
 if a.tests or a.tests_only:
  result=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s',str(ROOT/'tests'),'-p','test_*.py','-v'],cwd=ROOT,env=env)
  if result.returncode:return result.returncode
 if a.tests_only:return 0
 if not a.data_root:p.error('--data-root is required; benchmark data/logs are external')
 if len(a.stages)!=len(set(a.stages)):p.error('Duplicate stage')
 if {'controlled','redundancy'}&set(a.stages) and not a.pro_catalog:p.error('--pro-catalog is required')
 if 'model_swap' in a.stages and not (a.identity_root and a.task_list_root):p.error('model_swap requires --identity-root and --task-list-root')
 if a.figures and set(a.stages)!=set(STAGES):p.error('Figures require all five stages to match')
 out=a.out.resolve();data=a.data_root.resolve()
 for protected in [data]+[ROOT/n for n in ('data','results','paper','src','scripts','tests','configs','third_party')]:
  protected=protected.resolve()
  if out==protected or out.is_relative_to(protected) or protected.is_relative_to(out):p.error('Use a separate output directory outside input/code directories')
 if out.exists() and any(out.iterdir()):p.error('Use a new empty output directory')
 out.mkdir(parents=True,exist_ok=True)
 report=dict(status='RUNNING',stages=[],main_task_count=266,redundancy_sample_count=193,provider_calls=0,benchmark_reruns=0,input_directory=str(data),output_directory=str(out),analysis='Manuscript literals are validation targets; measurements must be supplied separately')
 def save():(out/'analysis_report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 for stage in a.stages:
  command=[sys.executable,'-B',str(ROOT/'scripts'/STAGES[stage]),'--data-root',str(data),'--out',str(out/stage)]
  if stage in {'controlled','redundancy'}:command+=['--pro-catalog',str(a.pro_catalog)]
  if stage=='model_swap':command+=['--identity-root',str(a.identity_root),'--task-list-root',str(a.task_list_root)]
  run=subprocess.run(command,cwd=ROOT,env=env)
  verification=out/stage/'verification.json';result=json.loads(verification.read_text()) if verification.exists() else {}
  status=result.get('status','INPUT_ERROR');report['stages'].append(dict(stage=stage,returncode=run.returncode,status=status))
  if run.returncode or status!='MATCH':
   report['status']='MISMATCH' if status=='MISMATCH' else 'INPUT_ERROR';save();return run.returncode or 1
 tables=out/'paper_tables';tables.mkdir()
 if 'controlled' in a.stages:
  for path in sorted((out/'controlled').glob('table_*.csv')):shutil.copyfile(path,tables/path.name)
 if 'observational' in a.stages:
  for panel in 'abc':shutil.copyfile(out/f'observational/table_01_panel_{panel}.csv',tables/f'table_01_panel_{panel}.csv')
 if 'repair' in a.stages:shutil.copyfile(out/'repair/component_activity.csv',tables/'table_02_activation_and_necessity.csv')
 if 'model_swap' in a.stages:shutil.copyfile(out/'model_swap/table_10_model_swap.csv',tables/'table_10_model_swap.csv')
 report['status']='MATCH' if set(a.stages)==set(STAGES) else 'PARTIAL_MATCH'
 if a.figures:
  run=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/generate_figures.py'),'--results',str(out),'--out',str(out/'figures')],cwd=ROOT,env=env)
  report['stages'].append(dict(stage='figures',returncode=run.returncode))
  if run.returncode:report['status']='FIGURE_ERROR';save();return run.returncode
 save();print(json.dumps(report,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
