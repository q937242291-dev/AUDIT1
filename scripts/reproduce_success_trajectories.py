#!/usr/bin/env python3
"""Offline Table 3 / Figure 3 reproduction (Python 3.10+, standard library only).

Estimator and RNG ordering are specified in docs/data_and_analysis.md.
No network, model, evaluator, or implicit source-directory dependency.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import sys
import unittest
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
ROLES = ('issue_specification', 'repository_orientation', 'code_search',
         'direct_file_read', 'history_lookup', 'environment_setup',
         'dependency_or_network', 'edit_or_patch', 'test_or_build',
         'diff_validation', 'feedback_recovery')
PAPER_ORDER = ('test_or_build', 'direct_file_read', 'edit_or_patch', 'code_search',
               'diff_validation', 'history_lookup', 'environment_setup',
               'issue_specification', 'dependency_or_network',
               'feedback_recovery', 'repository_orientation')
PANEL_B = ('code_search', 'direct_file_read', 'edit_or_patch', 'diff_validation',
           'history_lookup', 'environment_setup')
KEYS = (('claude-opus-5', 'high', 'mini_swe_agent_claude_opus_5_high'),
        ('claude-opus-5', 'max', 'mini_swe_agent_claude_opus_5_max'),
        ('claude-opus-5', 'xhigh', 'mini_swe_agent_claude_opus_5_xhigh'),
        ('gpt-5-6-sol', 'max', 'mini_swe_agent_gpt_5_6_sol_max'))


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    if not rows:
        raise ValueError('refusing empty output table: ' + Path(path).name)
    with Path(path).open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def sha256(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else hashlib.sha256(f.read()).hexdigest()


def truth(value):
    v = str(value).strip().lower()
    if v in ('true', '1', 'yes'):
        return True
    if v in ('false', '0', 'no'):
        return False
    raise ValueError('missing or invalid boolean: ' + repr(value))


def key(row):
    return tuple(row[k] for k in ('model', 'reasoning_effort', 'config'))


def label(k):
    return f'{k[0]}[{k[1]}]'


def wilson(k, n, z=1.96):
    if n <= 0 or not 0 <= k <= n:
        raise ValueError('invalid Wilson counts')
    p = k / n
    d = 1 + z*z/n
    c = (p + z*z/(2*n))/d
    m = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/d
    return max(0., c-m), min(1., c+m)


def interval(draws):
    s = sorted(draws)
    # Historical non-interpolating order statistics: 49 and 1950 for B=2000.
    return s[max(0, int(.025*len(s))-1)], s[min(len(s)-1, int(.975*len(s)))]


def bootstrap(values, rng, replicates):
    n = len(values)
    if not n:
        raise ValueError('no task clusters')
    return [sum(values[rng.randrange(n)] for _ in range(n))/n for _ in range(replicates)]


def group_tasks(rows):
    out = defaultdict(list)
    for row in rows:
        if not row['task_name']:
            raise ValueError('task_name missing; trial_name is not a task substitute')
        out[row['task_name']].append(row)
    return dict(sorted(out.items()))


def load_rows(path):
    rows = read_csv(path)
    if not rows:
        raise ValueError('empty trajectory input')
    seen = set()
    for row in rows:
        if row['trial_name'] in seen:
            raise ValueError('duplicate trial_name')
        seen.add(row['trial_name'])
        if not truth(row['official_success']) or not truth(row['public_log_complete']) or row['parse_status'] != 'parsed':
            raise ValueError('input must contain only complete parsed successes')
        if row['benchmark'] != 'DeepSWE v1.1' or key(row) not in KEYS:
            raise ValueError('unexpected benchmark or configuration')
        for role in ROLES:
            row[role+'_present'] = truth(row[role+'_present'])
        row['other_tool_step_present'] = truth(row['other_tool_step_present'])
        row['event_count'] = int(row['event_count'])
        if row['event_count'] < 0:
            raise ValueError('negative event_count')
    counts = Counter(key(r) for r in rows)
    if len(rows) != 1308 or any(counts[k] != 327 for k in KEYS):
        raise ValueError('paper cohort requires exactly four strata of 327 rows')
    return rows


def reproduce(rows, out, replicates=2000, seed=20260922):
    groups = {k: [r for r in rows if key(r) == k] for k in KEYS}
    tasks = {k: group_tasks(g) for k, g in groups.items()}
    rng = random.Random(seed)
    ratio_rng = random.Random(seed)
    prevalence, boots, ratio_boots, draws_out = [], [], [], []
    for k, group in sorted(groups.items()):
        for role in ROLES:
            field = role+'_present'
            hits = sum(r[field] for r in group)
            lo, hi = wilson(hits, len(group))
            prevalence.append(dict(configuration=label(k), model=k[0], reasoning_effort=k[1], config=k[2],
                                   process_unit=role, k=hits, n=len(group), prevalence=hits/len(group),
                                   wilson95_lower=lo, wilson95_upper=hi))
            any_values = [any(r[field] for r in t) for t in tasks[k].values()]
            draws = bootstrap(any_values, rng, replicates)
            blo, bhi = interval(draws)
            boots.append(dict(configuration=label(k), process_unit=role, estimator='task_any_successful_run',
                              task_count=len(any_values), positive_tasks=sum(any_values),
                              point=mean(any_values), bootstrap95_lower=blo, bootstrap95_upper=bhi,
                              replicates=replicates, seed=seed))
            cluster_counts = [(sum(r[field] for r in t), len(t)) for t in tasks[k].values()]
            ratio_draws = []
            for _ in range(replicates):
                sampled = [cluster_counts[ratio_rng.randrange(len(cluster_counts))] for _ in cluster_counts]
                ratio_draws.append(sum(a for a, b in sampled)/sum(b for a, b in sampled))
            rlo, rhi = interval(ratio_draws)
            ratio_boots.append(dict(configuration=label(k), process_unit=role,
                                    estimator='trajectory_prevalence_resample_whole_tasks',
                                    task_count=len(cluster_counts), point=hits/len(group),
                                    bootstrap95_lower=rlo, bootstrap95_upper=rhi, replicates=replicates, seed=seed))
            for i, (a, b) in enumerate(zip(draws, ratio_draws), 1):
                draws_out.append(dict(configuration=label(k), process_unit=role, replicate=i,
                                      task_any_prevalence=a, trajectory_prevalence=b))
    panel_a = []
    for role in PAPER_ORDER:
        ps = [x for x in prevalence if x['process_unit'] == role]
        bs = [x for x in boots if x['process_unit'] == role]
        rs = [x for x in ratio_boots if x['process_unit'] == role]
        hits = sum(x['k'] for x in ps)
        panel_a.append(dict(process_unit=role, k=hits, n=len(rows), pooled_prevalence=hits/len(rows),
                            stratum_min=min(x['prevalence'] for x in ps), stratum_max=max(x['prevalence'] for x in ps),
                            wilson95_min=min(x['wilson95_lower'] for x in ps), wilson95_max=max(x['wilson95_upper'] for x in ps),
                            task_any_bootstrap95_min=min(x['bootstrap95_lower'] for x in bs),
                            task_any_bootstrap95_max=max(x['bootstrap95_upper'] for x in bs),
                            trajectory_cluster_bootstrap95_min=min(x['bootstrap95_lower'] for x in rs),
                            trajectory_cluster_bootstrap95_max=max(x['bootstrap95_upper'] for x in rs),
                            estimator_warning='task_any intervals do not estimate trajectory prevalence'))
    panel_b = [dict(process_unit=role, **{label(k): next(x['prevalence'] for x in prevalence if x['configuration'] == label(k) and x['process_unit'] == role) for k in KEYS}) for role in PANEL_B]
    panel_c, sig_rows = [], []
    for k, group in list(groups.items()) + [(None, rows)]:
        signatures = Counter(tuple(role for role in ROLES if r[role+'_present']) for r in group)
        config = label(k) if k else 'Overall'
        panel_c.append(dict(configuration=config, n=len(group), signatures=len(signatures),
                            largest_signature_count=max(signatures.values()), largest_signature_share=max(signatures.values())/len(group),
                            mean_units=mean(sum(r[role+'_present'] for role in ROLES) for r in group),
                            mean_units_including_other_tool_step=mean(sum(r[role+'_present'] for role in ROLES)+r['other_tool_step_present'] for r in group),
                            total_events=sum(r['event_count'] for r in group), mean_events=mean(r['event_count'] for r in group)))
        if k is None:
            sig_rows = [dict(signature='|'.join(s), trajectory_count=n, share=n/len(group)) for s, n in sorted(signatures.items(), key=lambda x: (-x[1], x[0]))]
    pairs, pair_rows, pair_draws = [], [], []
    event_means = {k: {t: mean(r['event_count'] for r in g) for t, g in ts.items()} for k, ts in tasks.items()}
    for a, b in combinations(sorted(groups), 2):
        shared = sorted(set(tasks[a]) & set(tasks[b]))
        differences = [event_means[a][t]-event_means[b][t] for t in shared]
        draws = bootstrap(differences, rng, replicates)
        lo, hi = interval(draws)
        if b == KEYS[-1]:
            pairs.append(dict(stratum_a=label(a), stratum_b=label(b), shared_task_count=len(shared),
                              mean_difference_a_minus_b=mean(differences), bootstrap95_lower=lo, bootstrap95_upper=hi,
                              replicates=replicates, seed=seed, estimator='mean_of_task_mean_event_differences'))
            for t, d in zip(shared, differences):
                pair_rows.append(dict(stratum_a=label(a), stratum_b=label(b), task_name=t,
                                      a_mean_events=event_means[a][t], b_mean_events=event_means[b][t], difference_a_minus_b=d))
            pair_draws.extend(dict(stratum_a=label(a), stratum_b=label(b), replicate=i, mean_difference=d) for i, d in enumerate(draws, 1))
        # The source loop computes 15 metrics per pair with one shared RNG.
        # Consume the other 14 streams, without imputing their missing costs.
        for _ in range(14*replicates*len(shared)):
            rng.randrange(len(shared))
    backbone = sum(all(r[x+'_present'] for x in ('code_search', 'direct_file_read', 'edit_or_patch', 'test_or_build')) for r in rows)
    summary = dict(trajectory_count=len(rows), total_events=sum(r['event_count'] for r in rows),
                   signatures=len(sig_rows), backbone_count=backbone, backbone_share=backbone/len(rows),
                   task_counts={label(k): len(v) for k,v in tasks.items()},
                   replicates=replicates, seed=seed, bootstrap_rng='random.Random, sequential source ordering over four strata',
                   quantiles='sorted draws indices max(0,int(.025*B)-1), min(B-1,int(.975*B))',
                   repository_bootstrap='unavailable: no repository identifier', network_calls=0, model_calls=0)
    summary['estimators'] = {'trajectory_prevalence': 'fraction of successful runs with the unit',
        'task_any_prevalence': 'fraction of tasks with at least one positive successful run',
        'trajectory_cluster_bootstrap': 'resample tasks with all their successful runs'}
    out.mkdir(parents=True, exist_ok=True)
    for name, table in [('table3_panel_a', panel_a), ('table3_panel_b', panel_b), ('table3_panel_c', panel_c),
                        ('figure3_process_prevalence', [dict(process_unit=x['process_unit'], k=x['k'], n=x['n'], prevalence=x['pooled_prevalence'], band='high' if x['pooled_prevalence'] >= .8 else 'intermediate' if x['pooled_prevalence'] >= .2 else 'low') for x in panel_a]),
                        ('stratum_wilson', prevalence), ('task_any_bootstrap', boots),
                        ('trajectory_prevalence_cluster_bootstrap', ratio_boots), ('bootstrap_replicates', draws_out),
                        ('behavior_signatures', sig_rows), ('paired_task_event_deltas', pair_rows),
                        ('paired_event_summary', pairs), ('paired_event_bootstrap_replicates', pair_draws)]:
        write_csv(out / (name+'.csv'), table)
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    return summary


def audit_paper(a, b, c, pairs, summary):
    # Manuscript literals are comparison targets ONLY, never calculation inputs.
    expected_a = [
        (1308,100.,100.,100.,98.8,100.), (1251,95.6,87.8,98.8,83.8,99.5),
        (1224,93.6,88.1,96.6,84.1,98.1), (1168,89.3,67.,97.6,61.7,98.8),
        (654,50.,15.6,72.2,12.1,76.7), (466,35.6,22.3,41.3,18.1,46.7),
        (407,31.1,14.1,38.8,10.7,44.2), (282,21.6,20.8,22.,16.7,26.8),
        (116,8.9,8.,10.1,5.5,13.8), (28,2.1,1.8,2.4,.8,4.8), (0,0.,0.,0.,0.,1.2)]
    out = []
    def check(name, actual, expected, places=1):
        match = round(actual, places) == round(expected, places)
        out.append(dict(claim=name, computed=actual, manuscript=expected, difference=actual-expected,
                        comparison_decimal_places=places, status='MATCH' if match else 'MISMATCH'))
    for row, exp in zip(a, expected_a):
        for field, target in zip(('k','pooled_prevalence','stratum_min','stratum_max','wilson95_min','wilson95_max'), exp):
            check('Table3A/'+row['process_unit']+'/'+field, row[field]*(1 if field=='k' else 100), target, 0 if field=='k' else 1)
    for role, targets in {'code_search':(77.3,100.), 'diff_validation':(25.8,95.), 'history_lookup':(41.2,78.4), 'environment_setup':(23.7,73.2)}.items():
        row=next(x for x in a if x['process_unit']==role)
        for field, target in zip(('task_any_bootstrap95_min','task_any_bootstrap95_max'), targets):
            check('Table3A/'+role+'/'+field,row[field]*100,target)
    expected_b=((95.4,97.2,97.6,67.),(97.6,98.8,98.5,87.8),(93.,96.6,96.6,88.1),(47.1,72.2,65.1,15.6),(41.3,38.5,40.4,22.3),(34.3,38.8,37.3,14.1))
    for row, targets in zip(b,expected_b):
        for k,target in zip(KEYS,targets):
            check('Table3B/'+row['process_unit']+'/'+label(k),row[label(k)]*100,target)
    for row, targets in zip(c,((327,47,13.5,6.41,76.8),(327,43,17.1,6.76,103.1),(327,40,13.5,6.68,93.1),(327,65,21.4,5.27,63.1),(1308,98,14.8,6.28,84.))):
        for field,target in zip(('n','signatures','largest_signature_share','mean_units','mean_events'),targets):
            check('Table3C/'+row['configuration']+'/'+field,row[field]*(100 if field=='largest_signature_share' else 1),target,2 if field=='mean_units' else 0 if field in ('n','signatures') else 1)
        check('Table3C/'+row['configuration']+'/mean_units_including_other_tool_step',row['mean_units_including_other_tool_step'],targets[3],2)
    for row,targets in zip(pairs,((89,12.4,8.,17.4),(89,39.4,34.6,44.6),(88,28.2,23.3,33.4))):
        for field,target in zip(('shared_task_count','mean_difference_a_minus_b','bootstrap95_lower','bootstrap95_upper'),targets):
            check('RQ4/'+row['stratum_a']+'/'+field,row[field],target,0 if field=='shared_task_count' else 1)
    for field,target in [('trajectory_count',1308),('total_events',109911),('signatures',98),('backbone_count',1089)]:
        check(field,summary[field],target,0)
    return out


class ReproductionTests(unittest.TestCase):
    def test_wilson_extremes(self):
        self.assertAlmostEqual(wilson(0,327)[0],0.)
        self.assertAlmostEqual(wilson(327,327)[1],1.)
        self.assertAlmostEqual(wilson(0,327)[1],1-wilson(327,327)[0])
    def test_estimators_differ(self):
        clusters=[[True,False,False],[False]]
        self.assertEqual(mean(any(c) for c in clusters),.5)
        self.assertEqual(sum(map(sum,clusters))/sum(map(len,clusters)),.25)
    def test_percentiles_source_indices(self):
        self.assertEqual(interval(list(range(2000))),(49,1950))
    def test_seed_repeatability(self):
        self.assertEqual(bootstrap([1,2,4],random.Random(7),30),bootstrap([1,2,4],random.Random(7),30))
    def test_missing_flags_fail(self):
        with self.assertRaises(ValueError): truth('')
        with self.assertRaises(ValueError): truth('NA')
    def test_invalid_counts_fail(self):
        with self.assertRaises(ValueError): wilson(2,1)
    def test_task_means_not_run_difference(self):
        a=mean([mean([10,10,10]),mean([40])])
        self.assertEqual(a,25)
        self.assertNotEqual(a,mean([10,10,10,40]))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--input',type=Path)
    p.add_argument('--out',type=Path,help='default: ROOT/reproduced/observational')
    p.add_argument('--replicates',type=int,default=2000)
    p.add_argument('--seed',type=int,default=20260922)
    p.add_argument('--self-test',action='store_true')
    args=p.parse_args(argv)
    if args.self_test:
        return 0 if unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReproductionTests)).wasSuccessful() else 1
    if args.replicates<40:
        p.error('--replicates must be at least 40')
    source=args.input or args.root/'data/logs/deepswe_success_trajectories/success_trajectory_summary.csv'
    out=(args.out or args.root/'reproduced/observational').resolve()
    if out==source.resolve().parent:
        p.error('output cannot overwrite the input data directory')
    rows=load_rows(source)
    result=reproduce(rows,out,args.replicates,args.seed)
    result['input_sha256']=sha256(source)
    result['script_sha256']=sha256(Path(__file__))
    result['python_version']=sys.version.split()[0]
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
