"""Public deterministic JSON interface, with exact cached-output interventions.

    evaluate(snapshot: dict, condition: str = 'full_audit') -> dict
    evaluate_conditions(snapshot: dict, conditions: list[str] | None = None)
        -> dict[canonical_condition_name, result]

A matrix call validates/freeze-copies the input, runs all seven modules ONCE,
and passes a filtered tuple of those identical objects to each controller.
No controller receives raw evidence/history or disabled-output-derived flags.
The quality vector and trace are diagnostics and never controller inputs.
Results are independent JSON trees: modifying one cannot mutate another.

Result keys: schema_version, implementation_version, task_id, trial_id,
condition, enabled_modules, disabled_modules, model_config, controller_config,
module_parameters, quality_parameters, parameter_origin, snapshot_digest,
module_outputs_digest, all_module_outputs (seven), module_outputs (enabled),
decision, quality (grounding/path/verify/coherence/efficiency), trace.
Invalid schemas/conditions raise ValueError (BoundaryError for schema issues).
No file writes, empirical data reads, provider calls or environment access.
"""
from __future__ import annotations

from dataclasses import asdict
import json

from .conditions import available_conditions, load_condition
from .controllers import aggregate
from .modules import run_modules
from .quality import measure_quality
from .schema import IMPLEMENTATION_VERSION, MODULE_NAMES, Snapshot, digest


def evaluate_conditions(snapshot: dict, conditions: list[str] | None = None) -> dict[str, dict]:
    names = available_conditions() if conditions is None else conditions
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise ValueError('conditions must be a list of registered names or null')
    registrations = [load_condition(name) for name in names]
    if len({item.name for item in registrations}) != len(registrations):
        raise ValueError('duplicate condition names or aliases in a matrix')
    source = Snapshot.from_dict(snapshot)
    source_digest = source.digest()
    if not registrations:
        return {}
    first = registrations[0]
    for condition in registrations[1:]:
        if (condition.module_parameters != first.module_parameters
                or condition.controller_parameters != first.controller_parameters
                or condition.quality_parameters != first.quality_parameters):
            raise ValueError('matched conditions must share all parameters')
    outputs = run_modules(source, first.module_parameters)
    if tuple(output.module for output in outputs) != MODULE_NAMES:
        raise ValueError('registered module outputs must be complete and ordered')
    all_outputs = {output.module: output.as_dict() for output in outputs}
    output_digest = digest(all_outputs)
    quality = measure_quality(source, first.quality_parameters)
    trace = source.as_dict()['history']
    candidates = tuple(candidate.path for candidate in source.candidates)
    results = {}
    for condition in registrations:
        enabled = tuple(output for output in outputs if output.module in condition.enabled_modules)
        decision = aggregate(candidates, enabled, condition.controller, condition.controller_parameters)
        result = {
            'schema_version': 'audit_snapshot_v1', 'implementation_version': IMPLEMENTATION_VERSION,
            'task_id': source.task_id, 'trial_id': source.trial_id, 'condition': condition.name,
            'enabled_modules': list(condition.enabled_modules),
            'disabled_modules': [name for name in MODULE_NAMES if name not in condition.enabled_modules],
            'model_config': dict(source.model_config),
            'controller_config': {'controller': condition.controller, **asdict(condition.controller_parameters)},
            'module_parameters': asdict(condition.module_parameters),
            'quality_parameters': asdict(condition.quality_parameters),
            'parameter_origin': condition.parameter_origin,
            'snapshot_digest': source_digest, 'module_outputs_digest': output_digest,
            'all_module_outputs': all_outputs,
            'module_outputs': {output.module: all_outputs[output.module] for output in enabled},
            'decision': decision, 'quality': quality, 'trace': trace,
        }
        results[condition.name] = json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return results


def evaluate(snapshot: dict, condition: str = 'full_audit') -> dict:
    return next(iter(evaluate_conditions(snapshot, [condition]).values()))


evaluate_matrix = evaluate_conditions
