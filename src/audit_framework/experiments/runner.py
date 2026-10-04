"""Explicit execution, immutable component caches, and outcome-free runtime loading."""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
import json
import os
from pathlib import Path
from .adapters import core_adapter
from .contracts import digest, reject_outcomes, require, runtime_snapshot
from .planning import validate_plan
from .projections import identifier_mapping, mutate_snapshot, project_context

ENVELOPE_FIELDS = {'cohort', 'unit_id', 'snapshot', 'repository', 'context_sources',
                   'identifier_vocabulary', 'legal_history_chars'}
REPOSITORY_FIELDS = {'repo', 'base_commit', 'state_hash', 'root'}


def load_runtime_inputs(path: Path) -> dict[tuple[str, str], dict]:
    inputs = {}
    for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        require(isinstance(record, dict) and not set(record) - ENVELOPE_FIELDS,
                f'Unregistered runtime envelope field at line {n}')
        reject_outcomes(record, 'runtime_envelope')
        for field in ('cohort', 'unit_id'):
            require(isinstance(record.get(field), str) and record[field], f'Missing {field} at line {n}')
        runtime_snapshot(record.get('snapshot', {}))
        repository = record.get('repository', {})
        require(isinstance(repository, dict) and not set(repository) - REPOSITORY_FIELDS,
                'Repository binding contains unknown fields')
        for field in ('repo', 'base_commit', 'state_hash'):
            require(isinstance(repository.get(field), str) and repository[field], f'Missing repository {field}')
        key = (record['cohort'], record['unit_id'])
        require(key not in inputs, f'Duplicate runtime unit: {key}')
        inputs[key] = deepcopy(record)
    return inputs


def _bind(job: dict, envelope: dict) -> dict:
    snapshot = runtime_snapshot(envelope['snapshot'])
    require(snapshot['task_id'] == job['instance_id'], 'Runtime task differs from registered task')
    require(snapshot.get('trial_id', 'default') == job['unit_id'], 'Runtime trial must equal registered unit_id')
    repository = envelope['repository']
    unit = job['unit']
    for key in ('repo', 'base_commit'):
        expected = unit.get(key, unit.get('repository') if key == 'repo' else None)
        if expected:
            require(repository[key] == expected, f'Runtime {key} differs from corpus registration')
    if unit.get('source_commit'):
        require(repository['state_hash'] == unit['source_commit'], 'Replay state differs from checkpoint source commit')
    return snapshot


def _resolved_model(plan: dict, condition: dict, snapshot: dict, adapter, environment: dict) -> str:
    alias = condition['model_alias']
    variable = plan['model_aliases'][alias]
    value = environment.get(variable)
    bound = snapshot.get('model_config', {}).get('model')
    if getattr(adapter, 'requires_model', True):
        require(isinstance(value, str) and value.strip(), f'Execution requires environment alias {variable}')
    elif not value:
        value = bound or 'deterministic-core'
    if bound and condition['pipeline'] != 'path_verifier':
        require(bound == value, 'Snapshot and execution model differ')
    return value


def _row(job: dict, envelope: dict, model: str, result: dict | None = None,
         *, status: str = 'completed', error: str | None = None) -> dict:
    repository = envelope['repository']
    row = {k: job[k] for k in ('job_id', 'experiment', 'cohort', 'unit_id', 'instance_id',
        'replicate', 'checkpoint_id', 'endpoint', 'condition_id', 'protocol_sha256', 'prompt_template_sha256')}
    row.update({'status': status, 'base_commit': repository['base_commit'],
                'repository_state': repository['state_hash'],
                'solver_model': envelope['snapshot'].get('model_config', {}).get('model', model),
                'execution_model': model, 'snapshot_sha256': digest(envelope['snapshot'])})
    if result is not None:
        row['result'] = deepcopy(result)
    if error is not None:
        row['error'] = error
    return row


def execute_plan(plan: dict, inputs: dict, *, evaluate=None, execute: bool = False,
                 environment: dict | None = None, cache: dict | None = None) -> dict:
    """Call real adapters only after explicit activation; never read outcome rows.

    evaluate(snapshot, condition) -> dict is the callback contract. Component
    adapters must additionally expose evaluate_grid to guarantee one module pass.
    An explicit adapter error is recorded for every affected scheduled row.
    """
    require(execute is True, 'Execution is opt-in; pass execute=True or use the CLI --execute flag')
    validate_plan(plan)
    adapter = core_adapter if evaluate is None else evaluate
    require(callable(adapter), 'Execution adapter must be callable')
    environment = dict(os.environ if environment is None else environment)
    store = {} if cache is None else cache
    groups = defaultdict(list)
    for job in plan['jobs']:
        groups[(job['experiment'], job['cohort'], job['unit_id'])].append(job)
    expected = {(j['cohort'], j['unit_id']) for j in plan['jobs']}
    require(expected <= set(inputs), f'Missing runtime assignments: {len(expected - set(inputs))}')
    # Complete preflight before any adapter/provider is called.
    resolved = {}
    for job in plan['jobs']:
        envelope = inputs[(job['cohort'], job['unit_id'])]
        reject_outcomes(envelope, 'runtime_envelope')
        snapshot = _bind(job, envelope)
        capabilities = getattr(adapter, 'capabilities', None)
        require(capabilities is None or job['condition']['pipeline'] in capabilities,
                f"Adapter cannot execute {job['condition']['pipeline']}; configure the correct harness")
        if job['experiment'] == 'component_ablation':
            require(callable(getattr(adapter, 'evaluate_grid', None)), 'Component execution requires cached evaluate_grid')
        resolved[job['job_id']] = _resolved_model(plan, job['condition'], snapshot, adapter, environment)
        if job['experiment'] == 'original_reduced_workflows':
            fixed = plan['workflow_config']['fixed']
            require(resolved[job['job_id']] == fixed['model'], 'Workflow model differs from recorded protocol')
            require(getattr(adapter, 'paper_protocol', None) == fixed, 'Bind an actual SWE-agent adapter to the fixed paper protocol')
    rows = []
    for (experiment, cohort, unit_id), jobs in groups.items():
        envelope = deepcopy(inputs[(cohort, unit_id)])
        original = _bind(jobs[0], envelope)
        prepared = []
        for job in jobs:
            condition = deepcopy(job['condition'])
            model = resolved[job['job_id']]
            condition['_runtime'] = {
                'model': model, 'parameters': deepcopy(plan['parameters']),
                'prompt_template': plan['prompt_templates'][condition['prompt_template']],
                'repository_root': envelope['repository'].get('root'),
                'repository_state': envelope['repository']['state_hash'],
                'endpoint': job['endpoint'], 'checkpoint_id': job['checkpoint_id'],
                'unit_id': unit_id, 'job_id': job['job_id'], 'unit': deepcopy(job['unit']),
                'fixed_workflow_protocol': deepcopy(plan['workflow_config']['fixed']) if plan.get('workflow_config') else None,
            }
            prepared.append(condition)
        if experiment == 'component_ablation':
            # Runtime configuration cannot drift since planning.
            from ..conditions import load_condition
            for condition in prepared:
                require(load_condition(condition['core_condition']).as_dict() == plan['core_conditions'][condition['id']],
                        'Core condition parameters changed after planning')
            require(len({resolved[j['job_id']] for j in jobs}) == 1, 'Component grid changes model')
            key = digest([original, envelope['repository'], plan['protocol_sha256'], prepared[0]['_runtime']['model']])
            try:
                if key not in store:
                    outputs = adapter.evaluate_grid(deepcopy(original), deepcopy(prepared))
                    require(set(outputs) == {j['condition_id'] for j in jobs}, 'Cached grid omitted a condition')
                    caches = [out.get('all_module_outputs') for out in outputs.values()]
                    require(all(isinstance(c, dict) and len(c) == 7 for c in caches), 'Missing complete module outputs')
                    require(len({digest(c) for c in caches}) == 1, 'Component intervention changed retained outputs')
                    store[key] = {'results': deepcopy(outputs), 'all_module_outputs': deepcopy(caches[0]),
                                  'module_outputs_sha256': digest(caches[0]), 'snapshot_sha256': digest(original)}
                saved = store[key]
                require(saved['snapshot_sha256'] == digest(original), 'Cache snapshot binding mismatch')
                require(saved['module_outputs_sha256'] == digest(saved['all_module_outputs']), 'Corrupt module cache')
                for job in jobs:
                    result = deepcopy(saved['results'][job['condition_id']])
                    require(result['all_module_outputs'] == saved['all_module_outputs'], 'Cached condition output differs')
                    row = _row(job, envelope, resolved[job['job_id']], result)
                    row['module_cache_key'] = key
                    row['all_module_outputs_sha256'] = saved['module_outputs_sha256']
                    rows.append(row)
            except Exception as error:
                rows.extend(_row(j, envelope, resolved[j['job_id']], status='error', error=f'{type(error).__name__}: {error}') for j in jobs)
            continue
        method_bundle = None
        if experiment == 'localization_methods' and callable(getattr(adapter, 'evaluate_methods', None)):
            try:
                method_bundle = adapter.evaluate_methods(deepcopy(original), deepcopy(prepared))
                require(set(method_bundle) == {c['id'] for c in prepared}, 'Method adapter omitted an output')
            except Exception as error:
                rows.extend(_row(j, envelope, resolved[j['job_id']], status='error', error=f'{type(error).__name__}: {error}') for j in jobs)
                continue
        for job, condition in zip(jobs, prepared):
            try:
                snapshot, visibility, mapping = deepcopy(original), None, None
                if 'projection' in condition:
                    snapshot, visibility = project_context(snapshot, condition['projection'], envelope.get('context_sources', {}),
                        max_chars=plan['parameters']['max_context_chars'], legal_history_chars=envelope.get('legal_history_chars'))
                if condition.get('representation') == 'identifier_mutation':
                    vocabulary = envelope.get('identifier_vocabulary')
                    require(isinstance(vocabulary, list) and vocabulary, 'Mutation requires a declared identifier vocabulary')
                    mapping = identifier_mapping(vocabulary)
                    snapshot = mutate_snapshot(snapshot, mapping)
                if condition['pipeline'] == 'path_verifier':
                    snapshot['model_config'] = {**snapshot.get('model_config', {}), 'model': resolved[job['job_id']]}
                reject_outcomes(snapshot, 'adapter_input')
                result = deepcopy(method_bundle[condition['id']]) if method_bundle is not None else adapter(deepcopy(snapshot), deepcopy(condition))
                require(isinstance(result, dict), 'Adapter must return a result object')
                status = result.get('status', 'completed')
                require(status in {'completed', 'error', 'incomplete', 'blocked'}, 'Unknown adapter completion status')
                if condition['pipeline'] == 'repair':
                    require(result.get('endpoint') == job['endpoint'], 'Repair adapter returned a different endpoint')
                    require('completion_reason' in result, 'Repair completion requires explicit reason accounting')
                row = _row(job, envelope, resolved[job['job_id']], result, status=status)
                row['model_input_sha256'] = digest(snapshot)
                if visibility is not None: row['input_visibility'] = visibility
                if mapping is not None: row['identifier_mapping'] = mapping
                rows.append(row)
            except Exception as error:
                rows.append(_row(job, envelope, resolved[job['job_id']], status='error', error=f'{type(error).__name__}: {error}'))
    require(len(rows) == plan['planned_jobs'] and len({r['job_id'] for r in rows}) == len(rows), 'Execution dropped or duplicated scheduled jobs')
    return {'schema_version': 1, 'mode': 'executed', 'plan_sha256': plan['plan_sha256'],
            'scheduled_n': len(rows), 'completed_n': sum(r['status'] == 'completed' for r in rows),
            'noncompleted_n': sum(r['status'] != 'completed' for r in rows),
            'rows': rows, 'component_caches': deepcopy(store)}
