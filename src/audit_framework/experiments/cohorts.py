"""Extract identity-only task registrations from the unchanged empirical corpus."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from .contracts import digest, require, reject_outcomes


SOURCES = {
    'progressive_context': ('controlled/progressive_context/summary/case_level_metrics.csv',
        'dataset_instance_id', ('seed',), ('condition', 'C0_issue_only')),
    'component_ablation': ('logs/component_ablation/component_ablation_case_metrics.jsonl',
        'instance_id', (), ('variant', 'full_v5')),
    'localization_methods': ('controlled/localization_methods/release/case_level_localization_results.csv',
        'instance_id', (), None),
    'matched_context': ('controlled/matched_context/scored/scored_rows.csv',
        'instance_id', ('replicate',), ('condition', 'c0_issue_only')),
    'input_projection': ('controlled/input_projection/summary/cell_level_metrics.csv',
        'task_id', ('seed', 'variant'), ('condition_id', 'C_future_scrubbed')),
    'search': ('controlled/tool_search/summary/paired_rows.csv',
        'instance_id', ('pair_key',), None),
    'representation': ('controlled/identifier_representation/summary/paired_rows.csv',
        'instance_id', ('replicate',), None),
    'audit_policy': ('logs/audit_policy/audit_policy_results.jsonl',
        'instance_id', ('replicate',), ('method_id', 'solver_only')),
    'path_verifier_verified_200': ('logs/model_swap/gpt_4_1/verified_200/localization_outputs.jsonl',
        'instance_id', (), None),
    'path_verifier_lite_300': ('logs/model_swap/gpt_4_1/lite_300/localization_outputs.jsonl',
        'instance_id', (), None),
    'history_replay': ('logs/trajectory_replay/multicheckpoint_replay.csv',
        'task_id', ('checkpoint_id',), ('agent_or_human', 'human')),
    'repair_bounded': ('logs/repair_endpoints/bounded/index.csv',
        'task_id', (), ('method', 'gold')),
    'repair_official': ('logs/repair_endpoints/official/index.csv',
        'task_id', (), ('branch', 'reference')),
}
EXPECTED_UNITS = dict(zip(SOURCES, (240, 60, 266, 40, 18, 280, 120, 30, 200, 300, 150, 21, 12)))


def read_records(path: Path) -> list[dict]:
    if path.suffix == '.jsonl':
        return [json.loads(s) for s in path.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def extract_cohort(name: str, data_root: Path) -> dict:
    relative, id_field, repeat_fields, selection = SOURCES[name]
    path = data_root / relative
    rows = read_records(path)
    selected = [(n, row) for n, row in enumerate(rows, 1)
                if selection is None or row.get(selection[0]) == selection[1]]
    units, seen = [], set()
    for ordinal, row in selected:
        instance_id = str(row.get(id_field) or '')
        require(instance_id and instance_id not in {'NA', 'None'}, f'Missing actual task ID: {relative}:{ordinal}')
        key = [instance_id, *(str(row[field]) for field in repeat_fields)]
        require(tuple(key) not in seen, f'Duplicate execution identity: {name} {key}')
        seen.add(tuple(key))
        unit = {'unit_id': digest([name, key])[:24], 'instance_id': instance_id,
                'source_key': key, 'source_row': ordinal,
                'replicate': str(row.get('replicate') or row.get('seed') or '1'),
                'checkpoint_id': str(row.get('checkpoint_id') or '')}
        for field in ('repo', 'repository', 'base_commit', 'source_commit', 'days_after_t0',
                      'seed', 'variant', 'pilot_task_id', 'pair_key'):
            value = row.get(field)
            if value not in (None, '', 'NA'):
                unit[field] = value
        units.append(unit)
    units.sort(key=lambda row: row['source_key'])
    require(len(units) == EXPECTED_UNITS[name], f'Unexpected {name} assignment count: {len(units)}')
    if name in EXPECTED_TASKS:
        require(len({u['instance_id'] for u in units}) == EXPECTED_TASKS[name], f'{name}: distinct task count does not match paper')
    return {'schema_version': 1, 'name': name, 'source': relative,
            'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'id_field': id_field, 'repeat_fields': list(repeat_fields),
            'selection': list(selection) if selection else None,
            'assignment_count': len(units),
            'task_ids': sorted({u['instance_id'] for u in units}), 'units': units}


def verify_cohort(cohort: dict, data_root: Path) -> None:
    if cohort.get('schema_version') == 2:
        verify_registration(cohort)
        return
    require(cohort['name'] not in BENCHMARK_COHORTS,
            'This cohort requires an external schema-2 official identity registration')
    actual = extract_cohort(cohort['name'], data_root)
    require(actual == cohort, f"Task registration no longer matches corpus: {cohort['name']}")


# Counts refer to actual identities; repeated executions cannot replace tasks.
EXPECTED_TASKS = {'localization_methods':266, 'component_ablation':60,
                  'matched_context':40, 'input_projection':18, 'audit_policy':30,
                  'path_verifier_verified_200':200, 'path_verifier_lite_300':300,
                  'original_reduced_workflows':266}
EXPECTED_UNITS['original_reduced_workflows'] = 266
BENCHMARK_COHORTS = {'localization_methods':'pro_python_266',
                    'original_reduced_workflows':'pro_python_266',
                    'path_verifier_verified_200':'verified',
                    'path_verifier_lite_300':'lite'}
for _n in (50,100,150,200):
    _name = f'path_verifier_lite_{_n}'
    SOURCES[_name] = (f'logs/model_swap/gpt_4_1/lite_{_n}/localization_outputs.jsonl','instance_id',(),None)
    EXPECTED_UNITS[_name] = EXPECTED_TASKS[_name] = _n
    BENCHMARK_COHORTS[_name] = 'lite'
UNIT_FIELDS = {'instance_id','unit_id','source_key','source_row','replicate',
               'checkpoint_id','repo','repository','base_commit','source_commit',
               'days_after_t0','seed','variant','pilot_task_id','pair_key'}

def seal_registration(name, units, *, source, catalog=None, selection=None):
    require(name in EXPECTED_UNITS, 'Unknown cohort')
    require(isinstance(source,str) and source, 'Record the actual identity source')
    projected = []
    for item in units:
        row = dict(item)
        reject_outcomes(row)
        require(not set(row)-UNIT_FIELDS, 'Identity registration contains unregistered fields')
        row['replicate'] = str(row.get('replicate','1'))
        row['checkpoint_id'] = str(row.get('checkpoint_id',''))
        row['source_key'] = row.get('source_key',[row.get('instance_id'),row['replicate'],row['checkpoint_id']])
        row['unit_id'] = digest([name,row['source_key']])[:24]
        projected.append(row)
    projected.sort(key=lambda r:r['source_key'])
    result = {'schema_version':2,'name':name,'source':source,
              'assignment_count':len(projected),
              'task_ids':sorted({r['instance_id'] for r in projected}),
              'units':projected,'selection':selection,'identity_catalog':catalog}
    result['registration_sha256'] = digest(result)
    verify_registration(result)
    return result

def verify_registration(registration):
    from .benchmarks import validate_catalog
    require(registration.get('schema_version')==2,'Unsupported registration schema')
    require(registration.get('registration_sha256')==digest({k:v for k,v in registration.items() if k!='registration_sha256'}),'Registration checksum mismatch')
    name = registration['name']
    require(name in EXPECTED_UNITS,'Unknown cohort')
    units = registration['units']
    require(len(units)==registration['assignment_count']==EXPECTED_UNITS[name],f'{name}: wrong assignment count')
    seen=set()
    for row in units:
        reject_outcomes(row)
        require(not set(row)-UNIT_FIELDS,'Registration must contain identities only')
        require(isinstance(row.get('instance_id'),str) and row['instance_id'],'Missing actual instance_id')
        key=row.get('source_key')
        require(isinstance(key,list) and key and key[0]==row['instance_id'],'Invalid execution identity')
        require(all(isinstance(x,str) for x in key),'Identity keys must be strings')
        require(digest(key) not in seen,'Duplicate execution identity');seen.add(digest(key))
        require(row.get('unit_id')==digest([name,key])[:24],'Invalid unit identity')
        require(isinstance(row.get('replicate'),str) and isinstance(row.get('checkpoint_id'),str),'Missing execution fields')
    task_ids=sorted({r['instance_id'] for r in units})
    require(task_ids==registration['task_ids'],'Registration task list mismatch')
    if name in EXPECTED_TASKS:
        require(len(task_ids)==EXPECTED_TASKS[name],f'{name}: repeated executions are not distinct tasks')
    catalog=registration.get('identity_catalog')
    if name in BENCHMARK_COHORTS:
        require(catalog is not None,'An official benchmark identity catalog is required')
    if catalog is not None:
        validate_catalog(catalog)
        if name in BENCHMARK_COHORTS:
            require(catalog['benchmark']==BENCHMARK_COHORTS[name],'Wrong benchmark membership')
        by_id={r['instance_id']:r for r in catalog['tasks']}
        require(set(task_ids)<=set(by_id),'Task outside the official catalog')
        for row in units:
            reference=by_id[row['instance_id']]
            require(row.get('repo')==reference['repo'] and row.get('base_commit')==reference['base_commit'],'Repository/base commit differs from official identity')
    if name=='path_verifier_verified_200':
        require(isinstance(registration.get('selection'),dict) and registration['selection'].get('method'),'Record actual Verified200 selection provenance')

def cohort_from_catalog(name, catalog, *, task_ids=None, selection=None):
    from .benchmarks import validate_catalog
    validate_catalog(catalog)
    ids=task_ids if task_ids is not None else [r['instance_id'] for r in catalog['tasks']]
    require(isinstance(ids,list) and len(ids)==len(set(ids)),'Duplicate selected task')
    by_id={r['instance_id']:r for r in catalog['tasks']}
    require(set(ids)<=set(by_id),'Selected task outside the official catalog')
    return seal_registration(name,[by_id[i] for i in ids],source=catalog['source']['url'],catalog=catalog,selection=selection)
