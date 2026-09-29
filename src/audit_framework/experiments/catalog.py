"""Explicit experiment definitions and configurable execution parameters."""
from __future__ import annotations
import json
from pathlib import Path
from .contracts import MODULES, require, validate_component_grid
from .projections import MATCHED, PROGRESSIVE, PROJECTIONS
from .policies import POLICIES, SOURCE_POLICIES

PACKAGE_ROOT = Path(__file__).resolve().parents[3]
CONFIG_ROOT = PACKAGE_ROOT / 'configs' / 'experiments'


def registered_definitions() -> dict:
    def arm(name, pipeline, **extra):
        return {'id': name, 'pipeline': pipeline, 'model_alias': 'base',
                'prompt_template': 'localization_v1', 'reasoning_effort': 'max', **extra}
    components = [arm('full_audit', 'component', core_condition='full_audit', source_condition_id='full_v5', paper_label='Full audit',
                      enabled_modules=list(MODULES), controller='full')]
    for module in MODULES:
        canonical = module
        source_module = 'path_verifier' if module == 'path_verification' else module
        components.append(arm('minus_' + module, 'component', core_condition='minus_' + canonical,
                              source_condition_id='no_' + source_module, paper_label='Minus ' + module.replace('_', ' '),
                              enabled_modules=[m for m in MODULES if m != module], controller='full'))
    components.append(arm('majority_controller', 'component', core_condition='majority_controller',
                          source_condition_id='majority_vote_controller', paper_label='Majority controller',
                          enabled_modules=list(MODULES), controller='majority'))
    validate_component_grid(components)
    definitions = {
        'progressive_context': {'cohorts': ['progressive_context'], 'conditions': [arm(n, 'one_shot', projection=n) for n in PROGRESSIVE]},
        'component_ablation': {'cohorts': ['component_ablation'], 'conditions': components},
        'localization_methods': {'cohorts': ['localization_methods'], 'conditions': [
            arm('one_shot', 'one_shot', source_condition_id='luna_one_shot', paper_label='One-shot'),
            arm('tool_search', 'tool_search', source_condition_id='luna_tool_search', paper_label='Tool-search'),
            arm('no_audit', 'no_audit', source_condition_id='shenji_no_audit', paper_label='No audit'),
            arm('full_audit', 'full_audit', source_condition_id='shenji_v3_full_audit', paper_label='Full audit'),
            arm('trust_first', 'trust_first', source_condition_id='shenji_v4_trust_first', paper_label='Trust-first')]},
        'matched_context': {'cohorts': ['matched_context'], 'conditions': [arm(n, 'one_shot', projection=n) for n in MATCHED]},
        'input_projection': {'cohorts': ['input_projection'], 'conditions': [arm(n, 'one_shot', projection=n) for n in PROJECTIONS]},
        'search': {'cohorts': ['search'], 'conditions': [arm('one_shot', 'one_shot'), arm('tool_search', 'tool_search')]},
        'representation': {'cohorts': ['representation'], 'conditions': [
            arm('natural', 'one_shot', representation='natural'),
            arm('identifier_mutation', 'one_shot', representation='identifier_mutation')]},
        'audit_policy': {'cohorts': ['audit_policy'], 'conditions': [arm(n, 'policy', policy=n,
            source_condition_id=SOURCE_POLICIES[n], paper_label=n.replace('_', ' ').capitalize()) for n in POLICIES]},
        'path_verifier_models': {'cohorts': ['path_verifier_common_200', 'path_verifier_common_300'],
            'conditions': [arm(alias, 'path_verifier', model_alias=alias) for alias in
                           ('path_4_1_mini', 'path_4_1', 'path_5_1')]},
        'history_replay': {'cohorts': ['history_replay'], 'endpoint': 'history_replay',
            'conditions': [arm('human', 'repair', patch_branch='reference'), arm('OrcaLoca', 'repair', patch_branch='agent')]},
        'repair_bounded': {'cohorts': ['repair_bounded'], 'endpoint': 'bounded_test',
            'conditions': [arm(n, 'repair', patch_branch=n) for n in ('baseline', 'gold', 'agent')]},
        'repair_official': {'cohorts': ['repair_official'], 'endpoint': 'official_resolution',
            'conditions': [arm(n, 'repair', patch_branch=n) for n in ('reference', 'agent')]},
    }
    for entry in definitions.values():
        entry['endpoint'] = entry.get('endpoint', 'localization')
        entry['completion_key'] = ['cohort', 'unit_id', 'condition_id', 'checkpoint_id', 'endpoint']
    return {'schema_version': 1, 'experiments': definitions,
            'model_aliases': {'base': 'AUDIT_BASE_MODEL', 'path_4_1_mini': 'AUDIT_PATH_MODEL_SMALL',
                              'path_4_1': 'AUDIT_PATH_MODEL_MEDIUM', 'path_5_1': 'AUDIT_PATH_MODEL_NEW'},
            'parameters': {'max_context_chars': 16000, 'max_tool_turns': 6, 'max_tool_chars': 8000,
                           'max_tool_matches': 20, 'audit_interval': 1,
                           'parameter_origin': 'configurable_execution_parameters'},
            'prompt_templates': {'localization_v1': 'prompts/localization_v1.txt'},
            'execution_policy': {'default': 'plan', 'automatic_retries': 0,
                                 'source_data_read_only': True, 'model_ids_from_environment': True}}


def load_registry(config_root: Path = CONFIG_ROOT) -> dict:
    registry = json.loads((config_root / 'registry.json').read_text(encoding='utf-8'))
    require(registry.get('schema_version') == 1, 'Unsupported experiment registry')
    require(set(registry['experiments']) == set(registered_definitions()['experiments']), 'Unregistered experiment set')
    validate_component_grid(registry['experiments']['component_ablation']['conditions'])
    for name, entry in registry['experiments'].items():
        ids = [c['id'] for c in entry['conditions']]
        require(len(ids) == len(set(ids)), f'Duplicate condition in {name}')
    return registry
