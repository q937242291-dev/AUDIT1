"""Render current Figures 3–6 only from successfully validated measurements."""
from __future__ import annotations
import argparse,csv,json
from pathlib import Path

def read(path):
 with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--results',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args(argv)
 for stage in ('controlled','observational','model_swap','repair','redundancy'):
  if json.loads((a.results/stage/'verification.json').read_text()).get('status')!='MATCH':raise ValueError('Figures require all stages to match the manuscript')
 import matplotlib
 matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.spines.top':False,'axes.spines.right':False})
 a.out.mkdir(parents=True,exist_ok=True)
 def save(fig,name):
  fig.tight_layout();fig.savefig(a.out/(name+'.pdf'),bbox_inches='tight');fig.savefig(a.out/(name+'.png'),dpi=200,bbox_inches='tight');plt.close(fig)
 rows=read(a.results/'observational/figure3_process_prevalence.csv');fig,ax=plt.subplots(figsize=(9,5))
 ax.barh([r['process_unit'].replace('_',' ') for r in rows][::-1],[100*float(r['prevalence']) for r in rows][::-1],color='#3578a4');ax.set_xlabel('Observed prevalence among 1,308 successful trajectories (%)');save(fig,'figure_03_process_prevalence')
 methods=read(a.results/'controlled/table_06_localization_methods.csv');replay=read(a.results/'controlled/table_11_history_replay.csv');fig,axes=plt.subplots(1,2,figsize=(11,4))
 for r in methods:axes[0].scatter(float(r['mean_tokens']),100*float(r['file_hit_1']));axes[0].annotate(r['method'],(float(r['mean_tokens']),100*float(r['file_hit_1'])),xytext=(3,3),textcoords='offset points')
 axes[0].set(xlabel='Mean tokens per task',ylabel='Hit@1 (%)',title='Localization methods (266 tasks)')
 failed=[r for r in replay if r['category']!='completed'];axes[1].barh([r['label'] for r in failed][::-1],[int(r['rows']) for r in failed][::-1]);axes[1].set(xlabel='Noncompleted replay rows',title='Replay non-completion (224 rows)');save(fig,'figure_04_methods_and_replay')
 fig,axes=plt.subplots(2,2,figsize=(12,8));policy=read(a.results/'controlled/table_09_audit_policy.csv')
 for r in policy:axes[0,0].scatter(float(r['mean_tokens']),100*float(r['file_hit_1']));axes[0,0].annotate(r['label'],(float(r['mean_tokens']),100*float(r['file_hit_1'])),fontsize=7)
 axes[0,0].set(xlabel='Mean tokens per task',ylabel='Hit@1 (%)',title='(a) Policy sensitivity (30 tasks)')
 models=read(a.results/'model_swap/figure_05b_model_slices.csv')
 for model in sorted({r['model'] for r in models}):
  rs=sorted([r for r in models if r['model']==model],key=lambda r:int(r['n']));axes[0,1].plot([int(r['n']) for r in rs],[100*float(r['hit_1']) for r in rs],marker='o',label=model)
 axes[0,1].set(xlabel='Lite task slice',ylabel='Hit@1 (%)',title='(b) Path verifier model');axes[0,1].legend()
 checkpoints=read(a.results/'controlled/figure_05c_replay_checkpoints.csv');axes[1,0].bar([str(r['checkpoint_days']) for r in checkpoints],[100*float(r['completion_rate']) for r in checkpoints]);axes[1,0].set(xlabel='Checkpoint days',ylabel='Completion (%)',title='(c) Replay checkpoints')
 endpoints=read(a.results/'repair/repair_endpoint_rates.csv');axes[1,1].bar([r['endpoint']+'\n'+r['branch'] for r in endpoints],[float(r['percent']) for r in endpoints]);axes[1,1].tick_params(axis='x',labelsize=7);axes[1,1].set(ylabel='Resolution endpoint (%)',title='(d) Repair endpoints');save(fig,'figure_05_condition_sensitivity')
 rows=read(a.results/'redundancy/figure_06_redundancy_categories.csv');fig,axes=plt.subplots(1,3,figsize=(13,4),sharey=True)
 for ax,field,title in zip(axes,('step_share','absolute_redundancy_rate','within_category_redundancy_rate'),('All category events / steps','Redundancy labels / steps','Redundancy labels / category events')):
  ax.barh([r['category'] for r in rows][::-1],[100*float(r[field]) for r in rows][::-1]);ax.set(xlabel='Pooled event rate (%)',title=title)
 fig.suptitle('193 random Luna successful pairs from the 266-task Python subset; categories overlap');save(fig,'figure_06_behavior_redundancy')
 print('Figures 3–6 generated from validated evidence.');return 0
if __name__=='__main__':raise SystemExit(main())
