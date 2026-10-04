"""Table 10 / Figure 5(b); verify actual Verified/Lite identity membership."""
from __future__ import annotations
import argparse,csv,json,sys
from pathlib import Path
from statistics import mean
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from audit_framework.experiments.benchmarks import read_catalog
from audit_framework.experiments.cohorts import verify_registration
from audit_framework.experiments.contracts import require
MODELS={'gpt_4_1_mini':'gpt-4.1-mini','gpt_4_1':'gpt-4.1','gpt_5_1':'gpt-5.1'}
SLICES=['verified_200']+[f'lite_{n}' for n in (50,100,150,200,300)]

def write(path,rows):
 require(rows,'Cannot emit empty evidence');path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rows for k in r)));w.writeheader();w.writerows(rows)

def validate_rows(rows,catalog,n):
 require(len(rows)==len({r['instance_id'] for r in rows})==n,'Distinct task denominator mismatch')
 official={r['instance_id']:r for r in catalog['tasks']}
 for r in rows:
  require(r['instance_id'] in official,'Task outside benchmark catalog')
  for field in ('repo','base_commit'):require(r.get(field)==official[r['instance_id']][field],f'Changed official {field}')
  require(isinstance(r.get('found_files'),list) and isinstance(r.get('gold_files'),list),'Missing actual file predictions/targets')
  tokens=r.get('usage',{}).get('total_tokens');require(type(tokens) is int and tokens>=0,'Missing actual usage; cannot impute zero')
 return {r['instance_id'] for r in rows}

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--data-root',type=Path,required=True);p.add_argument('--identity-root',type=Path,required=True);p.add_argument('--task-list-root',type=Path,required=True);p.add_argument('--out',type=Path)
 a=p.parse_args(argv);out=a.out or a.root/'outputs/model_swap'
 catalogs={k:read_catalog(a.identity_root/(k+'_catalog.json')) for k in ('verified','lite')}
 require(all(catalogs[k]['benchmark']==k for k in catalogs),'Benchmark catalog label mismatch')
 registration=json.loads((a.task_list_root/'path_verifier_verified_200.json').read_text());verify_registration(registration)
 require(registration['identity_catalog']==catalogs['verified'],'Verified200 registration/catalog differs')
 summaries=[];checks=[];individual=[];slice_ids={}
 expected={'verified_200':[(.785,1258),(.795,1256),(.795,1264)],'lite_300':[(250/300,922),(250/300,922),(250/300,928)]}
 for model_index,(folder,model) in enumerate(MODELS.items()):
  for slice_name in SLICES:
   benchmark='verified' if slice_name.startswith('verified') else 'lite';n=int(slice_name.rsplit('_',1)[1]);catalog=catalogs[benchmark]
   path=a.data_root/'logs/model_swap'/folder/slice_name/'localization_outputs.jsonl'
   rows=[json.loads(s) for s in path.read_text(encoding='utf-8-sig').splitlines() if s.strip()];ids=validate_rows(rows,catalog,n)
   if slice_name in slice_ids:require(ids==slice_ids[slice_name],'Model swaps must use the same selected tasks')
   slice_ids[slice_name]=ids
   if benchmark=='verified':require(ids==set(registration['task_ids']),'Predictions differ from actual random Verified200 selection')
   if slice_name=='lite_300':require(ids=={r['instance_id'] for r in catalog['tasks']},'Lite300 must cover the full benchmark')
   metadata=json.loads(path.with_name('run_metadata.json').read_text())
   require(metadata.get('model')==model and metadata.get('changed_component')=='path_audit_llm_only' and metadata.get('catalog_sha256')==catalog['catalog_sha256'],'Missing model/role/catalog provenance')
   fixed=metadata.get('fixed_protocol');require(isinstance(fixed,dict) and fixed and all(fixed.values()),'Record fixed upstream model/harness/prompt/toolset/repository/evaluation identity')
   if model_index==0:slice_ids[slice_name+'_protocol']=fixed
   else:require(fixed==slice_ids[slice_name+'_protocol'],'Model swap changes upstream protocol')
   def hit(row,k):return int(bool(set(row['found_files'][:k]) & set(row['gold_files'])))
   row=dict(model=model,source_slice=slice_name,n=n,unique_tasks=n,hit_1=mean(hit(r,1) for r in rows),hit_3=mean(hit(r,3) for r in rows),mean_total_tokens=sum(r['usage']['total_tokens'] for r in rows)/n,changed_component='path_audit_llm_only',dataset_membership='verified_against_frozen_catalog')
   summaries.append(row)
   if slice_name in expected:
    target=expected[slice_name][model_index]
    for field,want,tol in [('hit_1',target[0],.00051),('mean_total_tokens',target[1],.50001)]:checks.append(dict(claim=f'Table10/{model}/{slice_name}/{field}',actual=row[field],manuscript=want,tolerance=tol,status='MATCH' if abs(row[field]-want)<=tol else 'MISMATCH'))
   for r in rows:individual.append(dict(model=model,source_slice=slice_name,instance_id=r['instance_id'],repo=r['repo'],hit_1=hit(r,1),hit_3=hit(r,3),total_tokens=r['usage']['total_tokens']))
 write(out/'table_10_model_swap.csv',[r for r in summaries if r['source_slice'] in expected]);write(out/'figure_05b_model_slices.csv',[r for r in summaries if r['source_slice'].startswith('lite_')]);write(out/'model_swap_scored_predictions.csv',individual);write(out/'manuscript_comparisons.csv',checks)
 result=dict(status='MATCH' if checks and all(r['status']=='MATCH' for r in checks) else 'MISMATCH',combinations=len(summaries),checks=len(checks),mismatches=[r for r in checks if r['status']!='MATCH'],provider_calls=0,benchmark_reruns=0)
 (out/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));return 0 if result['status']=='MATCH' else 1
if __name__=='__main__':raise SystemExit(main())
