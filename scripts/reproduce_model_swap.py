"""Recompute Table 10 / Figure 7(b) from recovered localization predictions.

Only the path-audit LLM was changed. Shared upstream calls and token costs remain
in each row. CommonN denotes a source-defined task slice, not independently
verified membership in the SWE-bench Verified/Lite dataset releases.
"""
import argparse, csv, json
from collections import Counter
from pathlib import Path
from statistics import mean

def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--out',type=Path)
    a=p.parse_args();out=a.out or a.root/'reproduced/model_swap'
    summaries=[];checks=[];individual=[]
    for path in sorted((a.root/'data/logs/model_swap').glob('*/*/localization_outputs.jsonl')):
        model=path.parent.parent.name; n=int(path.parent.name.split('_')[-1])
        rows=[json.loads(s) for s in path.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
        if len(rows)!=n or len({r['instance_id'] for r in rows})!=n:
            raise ValueError(f'Invalid distinct-task denominator: {model}, {n}')
        recorded=json.loads(path.with_name('recorded_summary.json').read_text(encoding='utf-8-sig'))
        def hit(row,k): return int(bool(set(row['found_files'][:k]) & set(row['gold_files'])))
        token_total=sum(r['usage']['total_tokens'] for r in rows)
        summary=dict(model=model,source_slice=f'Common{n}',n=n,unique_tasks=n,
          hit_1=mean(hit(r,1) for r in rows),hit_3=mean(hit(r,3) for r in rows),
          mean_total_tokens=token_total/n,
          path_audit_mean_tokens=sum(r.get('path_audit_usage',{}).get('total_tokens',0) for r in rows)/n,
          path_audit_calls=sum(r.get('path_audit_status')=='ok' for r in rows),
          provider='third_party_openai_compatible_gateway',
          changed_component='path_audit_llm_only',dataset_membership='unverified_source_slice')
        summaries.append(summary)
        for metric,got,want,tol in [('Hit@1',summary['hit_1'],recorded['Hit@1'],0.000001),('Hit@3',summary['hit_3'],recorded['Hit@3'],0.000001),('total_tokens',token_total,recorded['tokens'],0)]:
            checks.append(dict(model=model,n=n,metric=metric,recomputed=got,recorded=want,match=abs(got-want)<=tol))
        for r in rows:
            individual.append(dict(model=model,source_slice=f'Common{n}',instance_id=r['instance_id'],repo=r.get('repo',''),hit_1=hit(r,1),hit_3=hit(r,3),total_tokens=r['usage']['total_tokens'],path_audit_status=r.get('path_audit_status','')))
    if len(summaries)!=15:raise ValueError('Expected 15 model/slice combinations')
    write(out/'table_10_model_swap.csv',[r for r in summaries if r['n'] in [200,300]])
    write(out/'figure_07b_model_slices.csv',summaries)
    write(out/'model_swap_scored_predictions.csv',individual)
    write(out/'recorded_summary_checks.csv',checks)
    result=dict(status='RECOMPUTED' if all(r['match'] for r in checks) else 'MISMATCH',combinations=len(summaries),checks=len(checks),rows=len(individual),boundary='File-ranking outcome recomputed; no independent verification of upstream leakage, provider identity, dataset membership, or full-system model replacement')
    (out/'verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result));return 0 if result['status']=='RECOMPUTED' else 1

if __name__=='__main__':raise SystemExit(main())
