"""Frozen external identities. Import and planning never download benchmark data."""
from __future__ import annotations
from copy import deepcopy
import json,re
from pathlib import Path
from .contracts import digest,require
BENCHMARKS={
 'pro_python_266':{'dataset':'ScaleAI/SWE-bench_Pro','config':'v1','revision':'2d52cb3df914a3fcf80c7f66738b3a88ae37fc50','release':'v1.0','split':'test','language_field':'repo_language','language':'python','expected_tasks':266,'url':'https://huggingface.co/datasets/ScaleAI/SWE-bench_Pro','version_url':'https://huggingface.co/datasets/ScaleAI/SWE-bench_Pro/tree/2d52cb3df914a3fcf80c7f66738b3a88ae37fc50/data/v1'},
 'verified':{'dataset':'SWE-bench/SWE-bench_Verified','config':'default','revision':None,'split':'test','expected_tasks':500,'url':'https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified'},
 'lite':{'dataset':'SWE-bench/SWE-bench_Lite','config':'default','revision':None,'split':'test','expected_tasks':300,'url':'https://huggingface.co/datasets/SWE-bench/SWE-bench_Lite'}}

def identity_catalog(rows,benchmark,*,revision=None):
 require(benchmark in BENCHMARKS,'Unknown benchmark')
 spec=deepcopy(BENCHMARKS[benchmark]);selected=revision or spec['revision']
 require(isinstance(selected,str) and re.fullmatch('[0-9a-f]{40}',selected),'An immutable dataset commit SHA is required')
 if benchmark=='pro_python_266':require(selected==spec['revision'],'Use the frozen V1 mirror commit')
 spec['revision']=selected;tasks=[];seen=set()
 for row in rows:
  require(isinstance(row,dict),'Dataset rows must be objects')
  if 'language_field' in spec:
   language=row.get(spec['language_field']);require(isinstance(language,str) and language,'Missing repo_language')
   if language.lower()!=spec['language']:continue
  task={k:row.get(k) for k in ('instance_id','repo','base_commit')}
  require(all(isinstance(v,str) and v for v in task.values()),'Missing task identity')
  require(task['instance_id'] not in seen,'Duplicate benchmark task');seen.add(task['instance_id']);tasks.append(task)
 require(len(tasks)==spec['expected_tasks'],f"{benchmark} requires {spec['expected_tasks']} distinct tasks; found {len(tasks)}")
 result={'schema_version':1,'benchmark':benchmark,'source':spec,'task_count':len(tasks),'tasks':sorted(tasks,key=lambda r:r['instance_id']),'contains_outcomes':False}
 result['catalog_sha256']=digest(result);return result

def validate_catalog(catalog):
 require(catalog.get('schema_version')==1 and catalog.get('contains_outcomes') is False,'Unsupported identity catalog')
 require(catalog.get('catalog_sha256')==digest({k:v for k,v in catalog.items() if k!='catalog_sha256'}),'Catalog checksum mismatch')
 rows=deepcopy(catalog['tasks']);benchmark=catalog['benchmark']
 if benchmark=='pro_python_266':
  for row in rows:row['repo_language']='python'
 require(identity_catalog(rows,benchmark,revision=catalog['source']['revision'])==catalog,'Catalog projection differs from its declaration')

def read_catalog(path):
 catalog=json.loads(Path(path).read_text(encoding='utf-8-sig'));validate_catalog(catalog);return catalog

def fetch_catalog(benchmark,*,revision=None):
 require(benchmark in BENCHMARKS,'Unknown benchmark');spec=BENCHMARKS[benchmark];selected=revision or spec['revision']
 require(isinstance(selected,str) and re.fullmatch('[0-9a-f]{40}',selected),'Provide an immutable --revision')
 if benchmark=='pro_python_266':require(selected==spec['revision'],'Pro V1 must use the pinned revision')
 try:from datasets import load_dataset
 except ImportError as error:raise ValueError('Explicit download requires: pip install datasets') from error
 rows=load_dataset(spec['dataset'],spec['config'],split=spec['split'],revision=selected)
 return identity_catalog((dict(row) for row in rows),benchmark,revision=selected)
