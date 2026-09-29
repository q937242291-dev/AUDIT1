"""Nine matched conditions with explicit output-removal semantics.

Parameters are explicit artifact configuration choices.
All nine JSON registrations must agree on module/controller/quality parameters;
only enabled_modules and controller may change. Aliases do not create conditions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from .schema import MODULE_NAMES


@dataclass(frozen=True)
class ModuleParameters:
    minimum_grounding_refs: int
    minimum_abstention_refs: int
    detour_window: int
    detour_repeat_threshold: int


@dataclass(frozen=True)
class ControllerParameters:
    hard_veto_modules: tuple[str, ...]
    evidence_precedence: tuple[str, ...]
    vote_rule: str
    candidate_tie_break: str
    abstain_tie_priority: str


@dataclass(frozen=True)
class QualityParameters:
    token_budget: float
    call_budget: float
    elapsed_ms_budget: float | None


@dataclass(frozen=True)
class Condition:
    name: str
    enabled_modules: tuple[str, ...]
    controller: str
    module_parameters: ModuleParameters
    controller_parameters: ControllerParameters
    quality_parameters: QualityParameters
    parameter_origin: str

    def as_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self)))


_NAMES = ('full_audit', *(f'minus_{m}' for m in MODULE_NAMES), 'majority_controller')
_CONFIG_DIR = Path(__file__).resolve().parents[2] / 'configs' / 'conditions'


def available_conditions() -> list[str]:
    """Return the nine canonical names in paper order (fresh list per call)."""
    return list(_NAMES)


def _canonical(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError('condition must be a registered name')
    aliases = {'full': 'full_audit', 'majority': 'majority_controller',
               'minus_path_verifier': 'minus_path_verification'}
    aliases.update({f'remove_{m}': f'minus_{m}' for m in MODULE_NAMES})
    name = aliases.get(name, name)
    if name not in _NAMES:
        raise ValueError(f'unknown condition {name!r}; choose from {_NAMES}')
    return name


def load_condition(name: str) -> Condition:
    name = _canonical(name)
    raw = json.loads((_CONFIG_DIR / f'{name}.json').read_text(encoding='utf-8'))
    required = {'name', 'enabled_modules', 'controller', 'module_parameters',
                'controller_parameters', 'quality_parameters', 'parameter_origin'}
    if set(raw) != required:
        raise ValueError('condition registration has missing or unknown fields')
    expected = tuple(m for m in MODULE_NAMES if name != f'minus_{m}')
    expected_controller = 'majority' if name == 'majority_controller' else 'full'
    if (raw['name'] != name or tuple(raw['enabled_modules']) != expected
            or raw['controller'] != expected_controller):
        raise ValueError('condition must change exactly its registered output/controller')
    if name != 'full_audit':
        full = json.loads((_CONFIG_DIR / 'full_audit.json').read_text(encoding='utf-8'))
        for key in ('module_parameters', 'controller_parameters', 'quality_parameters', 'parameter_origin'):
            if raw[key] != full[key]:
                raise ValueError(f'matched conditions must hold {key} fixed')
    module = ModuleParameters(**raw['module_parameters'])
    if any(type(v) is not int or v < 1 for v in asdict(module).values()):
        raise ValueError('module parameters must be positive integers')
    cp = raw['controller_parameters']
    controller = ControllerParameters(**{**cp,
        'hard_veto_modules': tuple(cp['hard_veto_modules']),
        'evidence_precedence': tuple(cp['evidence_precedence'])})
    for names in (controller.hard_veto_modules, controller.evidence_precedence):
        if len(names) != len(set(names)) or not set(names) <= set(MODULE_NAMES) - {'abstention'}:
            raise ValueError('invalid or repeated controller module names')
    if (controller.vote_rule != 'plurality' or controller.candidate_tie_break != 'lexical_path'
            or controller.abstain_tie_priority != 'first'):
        raise ValueError('unimplemented voting/tie policy')
    quality = QualityParameters(**raw['quality_parameters'])
    import math
    for field, value in asdict(quality).items():
        if field == 'elapsed_ms_budget' and value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('quality normalization budgets must be finite and positive')
    if not isinstance(raw['parameter_origin'], str) or not raw['parameter_origin'].strip():
        raise ValueError('parameter origin must be a nonempty provenance label')
    return Condition(name, expected, expected_controller, module, controller, quality, raw['parameter_origin'])
