"""Extract identity-only task registrations from the unchanged empirical corpus."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from .contracts import digest, require


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
    'path_verifier_common_200': ('logs/model_swap/gpt_4_1/common_200/localization_outputs.jsonl',
        'instance_id', (), None),
    'path_verifier_common_300': ('logs/model_swap/gpt_4_1/common_300/localization_outputs.jsonl',
        'instance_id', (), None),
    'history_replay': ('logs/trajectory_replay/multicheckpoint_replay.csv',
        'task_id', ('checkpoint_id',), ('agent_or_human', 'human')),
    'repair_bounded': ('logs/repair_endpoints/bounded/index.csv',
        'task_id', (), ('method', 'gold')),
    'repair_official': ('logs/repair_endpoints/official/index.csv',
        'task_id', (), ('branch', 'reference')),
}
EXPECTED_UNITS = dict(zip(SOURCES, (240, 60, 260, 40, 18, 280, 120, 30, 200, 300, 150, 21, 12)))


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
    return {'schema_version': 1, 'name': name, 'source': relative,
            'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'id_field': id_field, 'repeat_fields': list(repeat_fields),
            'selection': list(selection) if selection else None,
            'assignment_count': len(units),
            'task_ids': sorted({u['instance_id'] for u in units}), 'units': units}


def verify_cohort(cohort: dict, data_root: Path) -> None:
    actual = extract_cohort(cohort['name'], data_root)
    require(actual == cohort, f"Task registration no longer matches corpus: {cohort['name']}")
