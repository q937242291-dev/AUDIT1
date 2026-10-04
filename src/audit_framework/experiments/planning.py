"""Deterministic manifests: corpus identifiers are scheduling data, never prompts."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
from .catalog import CONFIG_ROOT, PACKAGE_ROOT, load_registry
from .cohorts import verify_cohort
from .contracts import digest, require


def build_plan(experiment: str = 'all', *, data_root: Path | None = None,
               config_root: Path = CONFIG_ROOT, limit_units: int | None = None,
               parameters: dict | None = None, task_list_root: Path | None = None, workflow_config: dict | None = None) -> dict:
    registry = load_registry(config_root)
    require(experiment == 'all' or experiment in registry['experiments'], f'Unknown experiment: {experiment}')
    require(limit_units is None or type(limit_units) is int and limit_units > 0, 'limit_units must be positive')
    root = Path(data_root or PACKAGE_ROOT / 'data')
    registrations = Path(task_list_root or config_root / 'task_lists')
    settings = {**registry['parameters'], **(parameters or {})}
    require(not set(settings) - set(registry['parameters']), 'Unregistered protocol parameters')
    for name, value in settings.items():
        if name != 'parameter_origin':
            require(type(value) is int and value > 0, f'{name} must be a positive integer')
    prompts = {name: (config_root / path).read_text(encoding='utf-8')
               for name, path in registry['prompt_templates'].items()}
    names = list(registry['experiments']) if experiment == 'all' else [experiment]
    if 'original_reduced_workflows' in names:
        from .workflows import validate_workflows
        validate_workflows(workflow_config)
    jobs, source_files, summaries, core_parameters = [], {}, {}, {}
    if 'component_ablation' in names:
        from ..conditions import load_condition
        for c in registry['experiments']['component_ablation']['conditions']:
            core_parameters[c['id']] = load_condition(c['core_condition']).as_dict()
    protocol_sha = digest({'registry': registry, 'parameters': settings, 'prompts': prompts,
                           'component_conditions': core_parameters, 'workflow_config': workflow_config})
    for name in names:
        entry = registry['experiments'][name]
        planned, tasks = 0, set()
        for cohort_name in entry['cohorts']:
            path = registrations / (cohort_name + '.json')
            require(path.is_file(), f'Missing external registration: {path}; use --task-list-root. No task IDs are fabricated.')
            cohort = json.loads(path.read_text(encoding='utf-8'))
            verify_cohort(cohort, root)
            source_files[cohort_name] = cohort.get('registration_sha256', cohort.get('source_sha256'))
            units = cohort['units'][:limit_units] if limit_units else cohort['units']
            for unit in units:
                tasks.add(unit['instance_id'])
                for condition in entry['conditions']:
                    selected_condition = deepcopy(condition)
                    if name == 'original_reduced_workflows':
                        selected_condition['workflow'] = deepcopy(workflow_config[condition['id']])
                    job = {'experiment': name, 'cohort': cohort_name,
                           'unit_id': unit['unit_id'], 'instance_id': unit['instance_id'],
                           'replicate': unit['replicate'], 'checkpoint_id': unit['checkpoint_id'],
                           'endpoint': entry['endpoint'], 'condition_id': condition['id'],
                           'condition': selected_condition, 'unit': deepcopy(unit),
                           'protocol_sha256': protocol_sha,
                           'prompt_template_sha256': digest(prompts[condition['prompt_template']]),
                           'status': 'planned'}
                    job['job_id'] = digest({k: job[k] for k in (
                        'experiment', 'cohort', 'unit_id', 'condition_id', 'checkpoint_id', 'endpoint', 'protocol_sha256')})
                    jobs.append(job)
                    planned += 1
        summaries[name] = {'planned_jobs': planned, 'unique_task_ids': len(tasks),
                           'condition_count': len(entry['conditions'])}
    require(len({j['job_id'] for j in jobs}) == len(jobs), 'Duplicate planned job identity')
    plan = {'schema_version': 1, 'mode': 'planned', 'protocol_sha256': protocol_sha,
            'parameters': settings, 'model_aliases': registry['model_aliases'], 'prompt_templates': prompts,
            'core_conditions': core_parameters, 'source_fingerprints': source_files, 'workflow_config': deepcopy(workflow_config),
            'summary': summaries, 'jobs': jobs, 'planned_jobs': len(jobs), 'provider_calls': 0}
    plan['plan_sha256'] = digest(plan)
    return plan


def validate_plan(plan: dict) -> None:
    require(plan.get('schema_version') == 1 and plan.get('mode') == 'planned', 'Not an experiment plan')
    require(plan.get('plan_sha256') == digest({k: v for k, v in plan.items() if k != 'plan_sha256'}),
            'Plan checksum does not match its contents')
    require(len(plan['jobs']) == plan['planned_jobs'], 'Plan job count changed')
    require(len({j['job_id'] for j in plan['jobs']}) == len(plan['jobs']), 'Duplicate job in plan')
