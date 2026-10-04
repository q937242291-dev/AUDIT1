"""Recompute manuscript tables from released row-level records, without providers.

Source labels are accepted as provenance keys; output labels follow the
manuscript. No missing measurements are imputed as zero.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from audit_framework.experiments.benchmarks import read_catalog


def read(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        if Path(path).suffix == ".jsonl":
            return [json.loads(line) for line in f if line.strip()]
        return list(csv.DictReader(f))


def write(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"Refusing to emit an empty evidence table: {path.name}")
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def num(value):
    if str(value).strip().lower() in {"true", "false"}:
        return float(str(value).strip().lower() == "true")
    if value is None or str(value).strip().lower() in {"", "na", "n/a", "none", "nan"}:
        raise ValueError("Required measurement is missing; it cannot become zero")
    return float(value)


def avg(rows, key):
    return mean(num(r[key]) for r in rows)


def groups(rows, key):
    result = defaultdict(list)
    for row in rows:
        result[row[key]].append(row)
    return result


def binary(value):
    if isinstance(value, bool):
        return int(value)
    if str(value).lower() in {"true", "false"}:
        return int(str(value).lower() == "true")
    result = num(value)
    if result not in {0, 1}:
        raise ValueError(f"Expected binary measurement, got {value!r}")
    return int(result)


def wilson(k, n):
    if not n:
        raise ValueError("Wilson interval requires a nonempty denominator")
    z = 1.959963984540054
    p = k / n
    d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d
    h = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return max(0, c-h), min(1, c+h)


def paired(control, treatment):
    if len(control) != len(treatment) or not control:
        raise ValueError("Paired vectors must be nonempty and equal length")
    gain = sum(a == 0 and b == 1 for a, b in zip(control, treatment))
    loss = sum(a == 1 and b == 0 for a, b in zip(control, treatment))
    discordant = gain + loss
    p = min(1.0, 2 * sum(math.comb(discordant, j) for j in range(min(gain, loss)+1)) / 2**discordant) if discordant else 1.0
    return dict(n=len(control), control_mean=mean(control), treatment_mean=mean(treatment),
                gain=gain, loss=loss, ties=len(control)-discordant,
                delta=(gain-loss)/len(control), exact_mcnemar_p=p)


def unique_index(rows, keys):
    result = {}
    for row in rows:
        key = tuple(str(row[k]) for k in keys)
        if key in result:
            raise ValueError(f"Duplicate analysis key: {key}")
        result[key] = row
    return result


METHOD_ALIASES = [(['luna_one_shot','one_shot'],'One-shot'),(['luna_tool_search','tool_search'],'Tool-search'),(['shenji_no_audit','audit_no_audit','no_audit'],'No audit'),(['shenji_v3_full_audit','audit_v3_full_audit','full_audit'],'Full audit'),(['shenji_v4_trust_first','audit_v4_trust_first','trust_first'],'Trust-first')]

def validate_distinct_grid(rows, condition_key, task_key, n, catalog=None):
    by_condition=groups(rows,condition_key)
    sets=[]
    for name, group in by_condition.items():
        unique_index(group,[task_key])
        ids={r[task_key] for r in group}
        if len(ids)!=n:raise ValueError(f'{name}: expected {n} distinct tasks; got {len(ids)}')
        sets.append(ids)
    if not sets or any(ids!=sets[0] for ids in sets):raise ValueError('Condition task sets differ')
    if catalog:
        if sets[0]!={r['instance_id'] for r in catalog['tasks']}:raise ValueError('Task set differs from frozen official identities')
    return sets[0]

def validate_method_grid(rows, catalog):
    validate_distinct_grid(rows,'method_id','instance_id',266,catalog)
    keys=set(groups(rows,'method_id'))
    if len(keys)!=5 or any(len(keys & set(aliases))!=1 for aliases,_ in METHOD_ALIASES):raise ValueError('Expected exactly five canonical methods')

def validate_component_fixed_outputs(rows):
    validate_distinct_grid(rows,'variant','instance_id',60)
    for task, group in groups(rows,'instance_id').items():
        if len(group)!=9:raise ValueError('Component grid requires nine conditions')
        for field in ('solver_model','repository_state','base_commit','prompt_template_sha256','snapshot_sha256'):
            values=[r.get(field) for r in group]
            if not all(values) or len(set(values))!=1:raise ValueError(f'{task}: missing/changed fixed {field}')
        hashes=[r.get('all_module_outputs_sha256') for r in group if r['status']=='completed']
        if not all(hashes) or len(set(hashes))!=1:raise ValueError('Removal/controller study must use the same recorded module outputs')

def write_verification(out, checks, datasets):
    write(out/'manuscript_comparisons.csv',checks)
    mismatches=[r for r in checks if r['status']!='MATCH']
    result=dict(status='MATCH' if checks and not mismatches else 'MISMATCH',checks=len(checks),mismatches=mismatches,datasets=datasets,provider_calls=0,benchmark_reruns=0,main_task_count=266,boundary='Reaggregation of supplied measurements; targets never create observations')
    (out/'verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--data-root",type=Path,required=True)
    parser.add_argument("--pro-catalog",type=Path,required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    data_root = args.data_root.resolve()
    pro_catalog = read_catalog(args.pro_catalog)
    if pro_catalog["benchmark"] != "pro_python_266": raise ValueError("Requires frozen Pro Python266 catalog")
    out = (args.out or root / "reproduced" / "controlled").resolve()
    checks, datasets = [], []

    def check(item, field, got, expected, tolerance=0):
        checks.append(dict(item=item, metric=field, actual=got, manuscript=expected,
                           difference=got-expected, tolerance=tolerance,
                           status="MATCH" if abs(got-expected) <= tolerance else "MISMATCH"))

    def register(layer, rows, task_key, condition_key, run_keys):
        unique_index(rows, run_keys)
        task_counts = Counter(str(r[task_key]) for r in rows)
        datasets.append(dict(layer=layer, row_count=len(rows), unique_tasks=len(task_counts),
                             condition_count=len(set(str(r[condition_key]) for r in rows)),
                             task_key=task_key, analysis_key=" + ".join(run_keys),
                             min_rows_per_task=min(task_counts.values()), max_rows_per_task=max(task_counts.values())))
        write(out / "task_lists" / f"{layer}.csv", [dict(task_id=k, row_count=v) for k,v in sorted(task_counts.items())])

    # Table 3: 120 distinct tasks x two seeds x five context arms.
    prog = read(data_root / "controlled/progressive_context/summary/case_level_metrics.csv")
    register("progressive_context", prog, "task_id", "condition", ["task_id", "seed", "condition"])
    prog_labels = ["Issue only", "Executable failure", "Structural localization", "Requirement and design", "Evidence bundle"]
    prog_rows = []
    for (condition, rows), label, expected in zip(sorted(groups(prog, "condition").items()), prog_labels,
        [(240, .317, .250, .992, 884), (240, .592, 98/240, 1, 1079), (240, .683, 111/240, .963, 1168), (240, .846, 169/240, 1, 1389), (240, .867, 173/240, .675, 1742)]):
        row = dict(condition=condition, label=label, n=len(rows), unique_tasks=len({r['task_id'] for r in rows}),
                   candidate_nonempty=avg(rows, "candidate_nonempty"), file_hit_1=avg(rows, "filehit_1_posthoc"),
                   file_hit_3=avg(rows, "filehit_3_posthoc"), file_hit_5=avg(rows, "filehit_5_posthoc"),
                   evidence_record_complete=avg(rows, "evidence_contract_satisfied"), mean_tokens=avg(rows, "total_tokens"))
        for key, value, tol in zip(["n", "candidate_nonempty", "file_hit_1", "evidence_record_complete", "mean_tokens"], expected, [0,.00051,.00051,.00051,.50001]):
            check(f"Table 3/{label}",key,row[key],value,tol)
        prog_rows.append(row)
    write(out / "table_03_progressive_context.csv", prog_rows)
    write(out / "progressive_repository_counts.csv", [dict(repository=k, rows=len(v), unique_tasks=len({r['task_id'] for r in v})) for k,v in sorted(groups(prog,"repository").items())])

    # Table 4: run-level paired effects; instance IDs expose repeat dependence.
    paired_rows = []
    for factor, path, a, b, key in [
        ("Search", "tool_search", "one_shot", "tool_search", "pair_key"),
        ("Representation", "identifier_representation", "natural", "identifier_mutation", "fork_id")]:
        rows = read(data_root / f"controlled/{path}/summary/paired_rows.csv")
        unique_index(rows, [key])
        write(out / "task_lists" / f"{path}.csv", [dict(instance_id=k, paired_runs=len(v)) for k,v in sorted(groups(rows,"instance_id").items())])
        datasets.append(dict(layer=path,row_count=len(rows),unique_tasks=len({r['instance_id'] for r in rows}),condition_count=2,task_key="instance_id",analysis_key=key,min_rows_per_task=min(Counter(r['instance_id'] for r in rows).values()),max_rows_per_task=max(Counter(r['instance_id'] for r in rows).values())))
        for cutoff, counts in zip([1,3,5], [(66,27),(79,22),(79,21)] if factor == "Search" else [(41,6),(49,9),(49,6)]):
            stat = paired([binary(r[f"{a}_file_hit_{cutoff}"]) for r in rows], [binary(r[f"{b}_file_hit_{cutoff}"]) for r in rows])
            row = dict(factor=factor,metric=f"Hit@{cutoff}",unique_tasks=len({r['instance_id'] for r in rows}),**stat,
                       inference_boundary="Run-level McNemar reconstruction; repeated task observations are not independent tasks")
            paired_rows.append(row)
            check(f"Table 4/{factor}/Hit@{cutoff}","gain",stat['gain'],counts[0])
            check(f"Table 4/{factor}/Hit@{cutoff}","loss",stat['loss'],counts[1])
            targets = [(280,.468,.607,.139),(280,.521,.725,.204),(280,.525,.732,.207)] if factor=='Search' else [(120,.258,.550,.292),(120,.325,.658,.333),(120,.325,.683,.358)]
            for field,expected in zip(('n','control_mean','treatment_mean','delta'),targets[[1,3,5].index(cutoff)]):
                check(f'Table 4/{factor}/Hit@{cutoff}',field,stat[field],expected,0 if field=='n' else .00051)
        # Descriptive task-mean deltas retain equal issue weights.
        taskmeans=[]
        for task, taskrows in sorted(groups(rows,"instance_id").items()):
            taskmeans.append(dict(instance_id=task,paired_runs=len(taskrows),**{
                f"delta_hit_{cutoff}":mean(num(r[f"{b}_file_hit_{cutoff}"])-num(r[f"{a}_file_hit_{cutoff}"]) for r in taskrows) for cutoff in [1,3,5]}))
        write(out / f"{path}_task_mean_effects.csv",taskmeans)
    write(out / "table_04_paired_search_representation.csv", paired_rows)

    # Table 5: incomplete rows stay visible and never enter paired outcomes.
    comp = read(data_root / "logs/component_ablation/component_ablation_case_metrics.jsonl")
    register("component_ablation", comp,"instance_id","variant",["instance_id","variant"])
    validate_component_fixed_outputs(comp)
    by_variant = groups(comp,"variant")
    baseline_name = "full_v5" if "full_v5" in by_variant else "full_audit"
    base = {r['instance_id']:r for r in by_variant[baseline_name] if r['status']=='completed'}
    comp_labels = [(baseline_name,"Full audit"),("no_grounding","- grounding"),("no_ownership","- ownership"),("no_contradiction","- contradiction"),("no_detour","- detour"),("no_path_verifier","- path verifier"),("no_memory","- memory"),("no_abstention","- abstention"),("majority_vote_controller","majority controller")]
    comp_rows=[]
    for (variant,label), exp in zip(comp_labels,[(60,18,0,0,0),(60,19,8,1,0),(60,18,4,0,0),(60,19,4,1,0),(60,18,5,0,0),(60,18,6,0,0),(58,19,5,1,0),(59,18,5,0,0),(60,17,4,0,1)]):
        complete=[r for r in by_variant[variant] if r['status']=='completed']
        aligned=[r for r in complete if r['instance_id'] in base]
        stat=paired([binary(base[r['instance_id']]['FileHit@1']) for r in aligned],[binary(r['FileHit@1']) for r in aligned])
        changed=sum(base[r['instance_id']]['top1_file']!=r['top1_file'] for r in aligned)
        row=dict(variant=variant,label=label,planned=len(by_variant[variant]),completed=len(complete),errors=len(by_variant[variant])-len(complete),hits=sum(binary(r['FileHit@1']) for r in complete),file_hit_1=avg(complete,'FileHit@1'),changed_top1=changed,improve=stat['gain'],regress=stat['loss'],pair_count=stat['n'],paired_baseline_rate=stat['control_mean'],paired_keep_effect=-stat['delta'],exact_mcnemar_p=stat['exact_mcnemar_p'],mean_tokens=avg(complete,'tokens'))
        row['wilson_low'],row['wilson_high']=wilson(row['hits'],row['completed'])
        comp_rows.append(row)
        check(f'Table 5/{label}','planned',row['planned'],60)
        for field,expected in zip(['completed','hits','changed_top1','improve','regress'],exp):
            check(f"Table 5/{label}",field,row[field],expected)
    write(out / "table_05_component_ablation.csv",comp_rows)
    write(out / "component_incomplete_rows.csv",[dict(instance_id=r['instance_id'],variant=r['variant'],status=r['status'],error=r.get('error','')) for r in comp if r['status']!='completed'])

    # Table 6: 266 unique issues, each measured under five methods.
    methods=read(data_root / "controlled/localization_methods/release/valid_completed_results.csv")
    register('localization_methods',methods,'instance_id','method_id',['instance_id','method_id'])
    validate_method_grid(methods,pro_catalog)
    method_groups=groups(methods,'method_id')
    aliases=METHOD_ALIASES
    method_rows=[]
    chosen={}
    for (keys,label),(hits,tokens,calls) in zip(aliases,[(58,3062,1.0),(40,19600,5.1),(27,22661,6.1),(43,23240,6.6),(41,23240,6.6)]):
        key=next(k for k in keys if k in method_groups)
        rows=method_groups[key]; chosen[label]={r['instance_id']:r for r in rows}
        row=dict(method=label,source_method_id=key,n=len(rows),hits=sum(binary(r['FileHit@1']) for r in rows),file_hit_1=avg(rows,'FileHit@1'),mean_tokens=avg(rows,'tokens'),calls_per_task=avg(rows,'calls'),process_valid_rate=avg(rows,'process_valid') if label=='Trust-first' else '')
        method_rows.append(row)
        check(f'Table 6/{label}','n',row['n'],266)
        check(f'Table 6/{label}','file_hit_1',row['file_hit_1'],hits/266,0.00051)
        if label=='Trust-first':check(f'Table 6/{label}','process_valid_rate',row['process_valid_rate'],.526,.00051)
        check(f'Table 6/{label}','hits',row['hits'],hits)
        check(f'Table 6/{label}','mean_tokens',row['mean_tokens'],tokens,.5)
        check(f'Table 6/{label}','calls_per_task',row['calls_per_task'],calls,.05001)
    write(out / 'table_06_localization_methods.csv',method_rows)
    common=sorted(set(chosen['No audit'])&set(chosen['Full audit']))
    stack=paired([binary(chosen['No audit'][k]['FileHit@1']) for k in common],[binary(chosen['Full audit'][k]['FileHit@1']) for k in common])
    write(out / 'full_audit_vs_no_audit.csv',[stack])
    check('Section 3.2/full-audit','n',stack['n'],266)
    check('Section 3.2/full-audit','gain',stack['gain'],16)
    check('Section 3.2/full-audit','loss',stack['loss'],0)

    # Table 7: 18 distinct tasks per condition; repeated seeds cannot replace tasks.
    projection=read(data_root / 'controlled/input_projection/summary/cell_level_metrics.csv')
    register('input_projection',projection,'task_id','condition_id',['task_id','seed','condition_id'])
    validate_distinct_grid(projection,'condition_id','task_id',18)
    p_groups=groups(projection,'condition_id'); projection_rows=[]
    for condition,label,issue in [('O_original_future_info','Original registered condition',1),('C_future_scrubbed','Future-scrubbed',1),('P_equal_length_legal_history','Equal-length legal history',1),('L_location_only','Location-only',0),('D_diff_only','Diff-only',0)]:
        rows=p_groups[condition]
        row=dict(condition=condition,label=label,n=len(rows),unique_tasks=len({r['task_id'] for r in rows}),**{key:avg(rows,key) for key in ['issue_visible','future_payload_visible','location_payload_visible','diff_payload_visible']})
        projection_rows.append(row)
        for field,expected in [('n',18),('issue_visible',issue),('future_payload_visible',0),('location_payload_visible',0),('diff_payload_visible',0)]:
            check(f'Table 7/{label}',field,row[field],expected)
    write(out / 'table_07_input_projection.csv',projection_rows)

    # Table 8 and Figure 8: cost/outcome marginal utility and dominance.
    matched=read(data_root / 'controlled/matched_context/scored/scored_rows.csv')
    register('matched_context',matched,'instance_id','variant_id',['instance_id','replicate','variant_id'])
    validate_distinct_grid(matched,'variant_id','instance_id',40)
    matched_rows=[]
    for (variant,rows),label,exp in zip(sorted(groups(matched,'variant_id').items()),['Issue only','Entity tree','Symbol evidence','Dependency and API','Structural bundle','Checkpoint history','Bounded full context'],[(.525,.6,.6,1349),(.45,.55,.55,1864),(.525,.65,.65,2746),(.525,.65,.65,4072),(.55,.675,.675,5807),(.5,.625,.625,5804),(.5,.625,.625,5878)]):
        row=dict(variant=variant,label=label,n=len(rows),**{f'file_hit_{k}':avg(rows,f'file_hit_{k}') for k in [1,3,5]},mean_tokens=avg(rows,'total_tokens'))
        row['wilson_low'],row['wilson_high']=wilson(sum(binary(r['file_hit_1']) for r in rows),len(rows))
        matched_rows.append(row)
        for field,expected,tol in zip(['file_hit_1','file_hit_3','file_hit_5','mean_tokens'],exp,[1e-10,1e-10,1e-10,.5]):
            check(f'Table 8/{label}',field,row[field],expected,tol)
    write(out/'table_08_matched_context.csv',matched_rows)
    mg=groups(matched,'variant_id'); mb={r['instance_id']:r for r in mg['c0_issue_only']}
    marginal=[]
    for row in matched_rows:
        pairs=mg[row['variant']]
        item=dict(variant=row['variant'],label=row['label'],n=row['n'],delta_tokens=row['mean_tokens']-matched_rows[0]['mean_tokens'])
        for k in [1,3,5]:
            p=paired([binary(mb[r['instance_id']][f'file_hit_{k}']) for r in pairs],[binary(r[f'file_hit_{k}']) for r in pairs])
            item.update({f'delta_hit_{k}':p['delta'],f'gain_hit_{k}':p['gain'],f'loss_hit_{k}':p['loss']})
            dominated=any(o['mean_tokens']<=row['mean_tokens'] and o[f'file_hit_{k}']>=row[f'file_hit_{k}'] and (o['mean_tokens']<row['mean_tokens'] or o[f'file_hit_{k}']>row[f'file_hit_{k}']) for o in matched_rows)
            item[f'nondominated_hit_{k}']=not dominated
        marginal.append(item)
    for row,(gain,loss) in zip(marginal,[(0,0),(7,10),(7,7),(7,7),(7,6),(7,8),(6,7)]):
        check('Table 8/'+row['label'],'gain_hit_1',row['gain_hit_1'],gain)
        check('Table 8/'+row['label'],'loss_hit_1',row['loss_hit_1'],loss)
    write(out/'diagnostic_context_marginal_utility.csv',marginal)

    # Table 9: only audit ranking, not three copies of each provider run.
    policy_all=read(data_root/'controlled/audit_policy/summary/audit_policy_ranking_metrics.csv')
    policy=[r for r in policy_all if r['ranking_layer']=='audit']
    register('audit_policy',policy,'instance_id','config_id',['run_id','ranking_layer'])
    validate_distinct_grid(policy,'config_id','instance_id',30)
    pg=groups(policy,'config_id'); policy_rows=[]
    policies=[('solver_only','Solver only',30,10678,1),('solver_plus_end_of_run_audit','End-of-run audit',27,10649,1),('solver_plus_evidence_grounded_intervention','Evidence-grounded intervention',29,10644,1),('solver_plus_full_shenji','Full audit',29,31681,2.67),('solver_plus_observe_only_shenji','Observe-only audit',30,35819,3.10),('solver_plus_online_generic_intervention','Online generic intervention',29,10644,1)]
    for key,label,exp_hits,exp_tokens,exp_calls in policies:
        if key not in pg:
            key=key.replace('shenji','audit')
        rows=pg[key]
        row=dict(config_id=key,label=label,n=len(rows),unique_tasks=len({r['instance_id'] for r in rows}),hits=sum(binary(r['FileHit@1']) for r in rows),file_hit_1=avg(rows,'FileHit@1'),mean_tokens=avg(rows,'total_tokens'),calls_per_task=avg(rows,'provider_call_count'))
        row['wilson_low'],row['wilson_high']=wilson(row['hits'],row['n'])
        policy_rows.append(row)
        for field,expected,tol in [('hits',exp_hits,0),('mean_tokens',exp_tokens,.5),('calls_per_task',exp_calls,.0051)]:
            check(f'Table 9/{label}',field,row[field],expected,tol)
    write(out/'table_09_audit_policy.csv',policy_rows)

    # Table 11: derive detailed statuses from original replay row + failure log.
    replay=read(data_root/'logs/trajectory_replay/multicheckpoint_replay.csv')
    register('history_replay',replay,'task_id','checkpoint_id',['task_id','agent_or_human','checkpoint_id'])
    classified=[]
    for row in replay:
        status=row['replay_status']; detail=row['failure_detail'].lower()
        if status=='checkpoint_replay_completed': category='completed'
        elif status=='source_unavailable_during_replay': category='source_unavailable'
        elif status=='task_setup_failure': category='task_setup_failure'
        elif 'already exists' in detail: category='future_target_already_exists'
        elif 'no such file or directory' in detail or 'does not exist' in detail: category='future_target_missing'
        else: category='future_patch_not_applicable'
        classified.append(dict(task_id=row['task_id'],branch=row['agent_or_human'],checkpoint_days=int(num(row['days_after_t0'])),recorded_status=status,derived_failure_category=category))
    counts=Counter(r['derived_failure_category'] for r in classified)
    labels=[('completed','Completed',76),('future_patch_not_applicable','Patch not applicable',135),('future_target_already_exists','Target already exists',4),('future_target_missing','Target missing',28),('source_unavailable','Source unavailable',37),('task_setup_failure','Setup failure',20)]
    replay_rows=[]
    for category,label,expected in labels:
        replay_rows.append(dict(category=category,label=label,rows=counts[category],denominator=len(replay),share=counts[category]/len(replay)))
        check(f'Table 11/{label}','rows',counts[category],expected)
    write(out/'table_11_history_replay.csv',replay_rows)
    write(out/'history_replay_classified_rows.csv',classified)
    timeline=[]
    for day,rows in sorted(groups(classified,'checkpoint_days').items()):
        completed=sum(r['derived_failure_category']=='completed' for r in rows)
        timeline.append(dict(checkpoint_days=day,completed=completed,n=len(rows),completion_rate=completed/len(rows),unique_tasks=len({r['task_id'] for r in rows})))
    write(out/'figure_05c_replay_checkpoints.csv',timeline)
    if [r['checkpoint_days'] for r in timeline]!=[7,30,90,180,365]:raise ValueError('Checkpoint schedule differs from paper')
    for row, expected in zip(timeline,[56.7,38.3,20.,6.7,5.]):
        check(f"Figure 5(c)/d{row['checkpoint_days']}",'n',row['n'],60)
        check(f"Figure 5(c)/d{row['checkpoint_days']}",'displayed_percentage',row['completion_rate']*100,expected,.05001)
    write(out/'dataset_denominators.csv',datasets)
    result=write_verification(out,checks,datasets)
    print(json.dumps(result,indent=2))
    return 0 if result['status']=='MATCH' else 1



if __name__=='__main__':
    raise SystemExit(main())
