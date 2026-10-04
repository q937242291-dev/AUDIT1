"""Figure 6 from paired workflow outcomes and successful trajectory records."""
from __future__ import annotations
import argparse,csv,json,random,sys,re
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from audit_framework.experiments.benchmarks import read_catalog
from audit_framework.experiments.contracts import digest,require
CATEGORIES=('Search / Exploration','Edit / Patch','Context / Information acquisition','Validation / Verification','Recovery / History')
FIXED=('model','reasoning_effort','harness','harness_revision','prompt_sha256','toolset_sha256','evaluation_protocol','repo','base_commit','repository_state')

def sha(value):return isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) is not None

def validate_outcomes(rows,catalog):
 require(catalog['benchmark']=='pro_python_266','Use pinned Pro Python266 identities')
 official={r['instance_id']:r for r in catalog['tasks']};by_id={r['instance_id']:r for r in rows}
 require(len(rows)==len(by_id)==266 and set(by_id)==set(official),'Full original/reduced ledger must cover every one of the 266 actual tasks')
 for task,row in by_id.items():
  require(row.get('model_role')=='GPT-5.6 Luna','Record the paper Luna model role')
  for arm in ('original','reduced'):
   run=row.get(arm);require(isinstance(run,dict),'Missing paired workflow outcome')
   require(run.get('status') in {'completed','error','incomplete','blocked'},'Missing explicit execution status')
   require((type(run.get('resolved')) is bool) if run['status']=='completed' else run.get('resolved') is None,'Incomplete outcomes must remain missing')
   require(all(run.get(k) for k in FIXED),'Missing fixed protocol identity')
   require(run['reasoning_effort']=='max' and run['harness']=='SWE-agent' and run['harness_revision']!='main','Freeze the actual Luna/max/SWE-agent protocol')
   require(sha(run['prompt_sha256']) and sha(run['toolset_sha256']),'Invalid fixed protocol hashes')
   for field in ('repo','base_commit'):require(run[field]==official[task][field],'Wrong official repository/base commit')
   if run['status']=='completed':require(sha(run.get('evaluator_report_sha256')),'Missing real evaluator report hash')
  for field in FIXED:require(row['original'][field]==row['reduced'][field],f'Pair changes fixed {field}')
 return by_id

def validate_selection(selection,by_id):
 ids=selection.get('selected_task_ids')
 require(isinstance(ids,list) and len(ids)==len(set(ids))==193 and set(ids)<=set(by_id),'Expected 193 distinct successful-pair identities matching the workflow ledger')
 require(selection.get('method')=='random_without_replacement' and selection.get('sampling_frame')=='luna_original_successes_in_pro_python_266','Record successful-pair selection provenance')
 require(type(selection.get('seed')) is int and isinstance(selection.get('rng'),str) and selection['rng'],'Missing actual random seed/RNG')
 eligible=sorted(task for task,row in by_id.items() if row['original']['status']=='completed' and row['original']['resolved'] is True)
 require(selection.get('eligible_task_ids_sha256')==digest(eligible),'Sampling frame digest mismatch')
 require(set(ids)<=set(eligible),'Selected original workflow failed')
 if selection['rng']=='python.random.Random':require(random.Random(selection['seed']).sample(eligible,193)==ids,'Selected IDs differ from recorded seed/RNG')
 else:require(sha(selection.get('source_selection_sha256')),'Provide the actual selection source hash for another RNG')
 for task in ids:require(by_id[task]['reduced']['status']=='completed' and by_id[task]['reduced']['resolved'] is True,'Figure6 requires both workflows to resolve each sampled issue')
 return set(ids)

def aggregate_steps(rows,selected):
 seen=set();observed=set();counts=Counter();redundant=Counter();omitted=0
 for row in rows:
  task=row.get('instance_id');require(task in selected,'Step outside the sampled successful task IDs');observed.add(task)
  require(isinstance(row.get('step_id'),str) and row['step_id'],'Missing actual step identity')
  key=(task,row['step_id']);require(key not in seen,'Duplicate normalized step');seen.add(key)
  categories=row.get('categories');require(isinstance(categories,list) and categories and len(categories)==len(set(categories)) and set(categories)<=set(CATEGORIES),'Unknown/duplicate behavior categories')
  require(type(row.get('omitted')) is bool,'Missing actual omission label')
  alignment=row.get('alignment');require(isinstance(alignment,dict) and alignment.get('normalizer_version') and alignment.get('method') and sha(alignment.get('source_sha256')),'Missing actual pair alignment provenance')
  require((row.get('reduced_step_id') is None) if row['omitted'] else (isinstance(row.get('reduced_step_id'),str) and bool(row['reduced_step_id'])),'Omission conflicts with reduced step alignment')
  counts.update(categories)
  if row['omitted']:redundant.update(categories);omitted+=1
 require(observed==selected,'Every sampled successful issue needs actual aligned steps')
 n=len(seen);require(n>0 and all(counts[c]>0 for c in CATEGORIES),'Empty category evidence')
 return [dict(category=c,all_events=counts[c],redundant_events=redundant[c],all_step_denominator=n,step_share=counts[c]/n,absolute_redundancy_rate=redundant[c]/n,within_category_redundancy_rate=redundant[c]/counts[c]) for c in CATEGORIES],dict(total_steps=n,redundancy_labels=sum(redundant.values()),unique_omitted_steps=omitted,redundancy_label_rate=sum(redundant.values())/n)

def read_jsonl(path):return [json.loads(s) for s in path.read_text(encoding='utf-8-sig').splitlines() if s.strip()]

def write(path,rows):
 require(rows,'No evidence rows');path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data-root',type=Path,required=True);p.add_argument('--pro-catalog',type=Path,required=True)
 p.add_argument('--outcomes',type=Path);p.add_argument('--steps',type=Path);p.add_argument('--selection',type=Path);p.add_argument('--out',type=Path,required=True)
 a=p.parse_args(argv);folder=a.data_root/'logs/redundancy';catalog=read_catalog(a.pro_catalog)
 by_id=validate_outcomes(read_jsonl(a.outcomes or folder/'workflow_outcomes.jsonl'),catalog)
 selection=json.loads((a.selection or folder/'success_sample.json').read_text());selected=validate_selection(selection,by_id)
 table,summary=aggregate_steps(read_jsonl(a.steps or folder/'aligned_steps.jsonl'),selected);checks=[]
 def compare(claim,actual,want,tolerance=0):checks.append(dict(claim=claim,actual=actual,manuscript=want,tolerance=tolerance,status='MATCH' if abs(actual-want)<=tolerance else 'MISMATCH'))
 for field,want in [('total_steps',20648),('redundancy_labels',7348),('redundancy_label_rate',.356)]:compare('Figure6/'+field,summary[field],want,.00051 if field.endswith('rate') else 0)
 for row,total,red,shares in zip(table,[8875,7849,6897,5794,776],[2654,1986,1358,None,None],[(43.,12.9,29.9),(38.,9.6,25.3),(33.4,6.6,19.7),(28.1,4.8,17.3),(3.8,1.7,45.1)]):
  compare('Figure6/'+row['category']+'/all_events',row['all_events'],total)
  if red is not None:compare('Figure6/'+row['category']+'/redundant_events',row['redundant_events'],red)
  for field,want in zip(('step_share','absolute_redundancy_rate','within_category_redundancy_rate'),shares):compare('Figure6/'+row['category']+'/'+field,100*row[field],want,.05001)
 # Approximate labels (~1,000 / ~350) are checked via the displayed rates.
 write(a.out/'figure_06_redundancy_categories.csv',table);write(a.out/'manuscript_comparisons.csv',checks)
 summary.update(status='MATCH' if checks and all(r['status']=='MATCH' for r in checks) else 'MISMATCH',full_task_count=266,sampled_successful_pairs=193,checks=len(checks),mismatches=[r for r in checks if r['status']!='MATCH'],provider_calls=0,benchmark_reruns=0,category_overlap=True,sampling_seed=selection['seed'],sampling_rng=selection['rng'],catalog_sha256=catalog['catalog_sha256'])
 (a.out/'verification.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary));return 0 if summary['status']=='MATCH' else 1
if __name__=='__main__':raise SystemExit(main())
