"""Pinned SWE-agent planning and the on_actions_generated hook bridge.

No model, environment, network, or subprocess is started by this module.
The caller supplies final-localization recognition, snapshot extraction,
and the callback that applies the selected decision to the outgoing step.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
from importlib import metadata
import json
import math
from pathlib import Path
from typing import Callable

from .upstream import source_info, verified_path


@dataclass(frozen=True)
class PinnedInvocation:
    repository: str
    commit: str
    install_requirement: str
    argv: tuple[str, ...]
    config_sha256: str
    prompt_sha256: str

    def as_dict(self) -> dict:
        result = asdict(self)
        result['argv'] = list(self.argv)
        return result


def build_swe_agent_invocation(*, config: str | Path, repository: str | Path,
        issue_file: str | Path, output_dir: str | Path, model: str,
        cost_limit: float, commit: str | None = None) -> PinnedInvocation:
    """Build upstream arguments. The bare upstream CLI does not attach AUDIT."""
    source = source_info('swe_agent')
    if commit is not None and commit != source['commit']:
        raise ValueError('All arms must use the pinned SWE-agent commit')
    if not isinstance(model, str) or not model.strip() or model.startswith('-'):
        raise ValueError('An explicit model name is required')
    if isinstance(cost_limit, bool) or not isinstance(cost_limit, (int, float)) or not math.isfinite(cost_limit) or cost_limit <= 0:
        raise ValueError('A finite positive per-instance cost limit is required')
    config, repository, issue_file, output_dir = map(Path, (config, repository, issue_file, output_dir))
    if not config.is_file() or not issue_file.is_file() or not repository.is_dir():
        raise ValueError('Config, repository and issue file must exist locally')
    if output_dir.resolve() == repository.resolve() or output_dir.resolve().is_relative_to(repository.resolve()):
        raise ValueError('Output must be outside the target repository')
    verified_path('swe_agent', 'sweagent/run/run_single.py')
    argv = ('sweagent', 'run', '--config', str(config), '--env.repo.path', str(repository),
            '--problem_statement.path', str(issue_file), '--agent.model.name', model,
            '--agent.model.per_instance_cost_limit', str(cost_limit), '--output_dir', str(output_dir),
            '--actions.open_pr=false', '--actions.apply_patch_locally=false')
    return PinnedInvocation(source['repository'], source['commit'],
        f"git+https://github.com/{source['repository']}.git@{source['commit']}", argv,
        hashlib.sha256(config.read_bytes()).hexdigest(), hashlib.sha256(issue_file.read_bytes()).hexdigest())


def validate_swe_agent_config(config: dict):
    """Use the installed pinned upstream config validator without starting a run."""
    assert_installed_swe_agent_pin()
    from sweagent.run.run_single import RunSingleConfig
    return RunSingleConfig.model_validate(deepcopy(config))


def assert_installed_swe_agent_pin() -> None:
    source = source_info('swe_agent')
    try:
        dist = metadata.distribution('sweagent')
        direct = json.loads(dist.read_text('direct_url.json') or '{}')
    except (metadata.PackageNotFoundError, ValueError) as exc:
        raise RuntimeError('Install the full SWE-agent package using the pinned git requirement') from exc
    url = direct.get('url', '').rstrip('/').removesuffix('.git')
    if (direct.get('vcs_info', {}).get('commit_id') != source['commit'] or
            url != f"https://github.com/{source['repository']}"):
        raise RuntimeError('Installed SWE-agent does not attest the official pinned commit via direct_url.json')


class PreFinalAuditHook:
    """Assess before executing a final-localization action.

snapshot_factory(agent, step) -> explicit core snapshot;
is_final_action(step) -> bool; apply_decision(step, selected_result) -> None.
All nine conditions are evaluated once against the same snapshot.
Only the selected result is passed to the applying callback.
"""
    def __init__(self, snapshot_factory: Callable, *, is_final_action: Callable,
                 apply_decision: Callable, condition: str = 'full_audit', evaluator: Callable | None = None):
        from ..conditions import load_condition
        self.condition = load_condition(condition).name
        if not all(callable(f) for f in (snapshot_factory, is_final_action, apply_decision)):
            raise ValueError('Snapshot extraction, final-action predicate, and decision application are required')
        self.snapshot_factory = snapshot_factory
        self.is_final_action = is_final_action
        self.apply_decision = apply_decision
        self.evaluator = evaluator
        self.agent = None
        self.records: list[dict] = []
        self._processed_step = None

    def on_init(self, *, agent):
        self.agent = agent

    def on_run_start(self):
        self.records.clear()
        self._processed_step = None

    def on_actions_generated(self, *, step):
        if not self.is_final_action(step):
            return
        if self.agent is None:
            raise RuntimeError('Attach the hook with agent.add_hook before use')
        if step is self._processed_step:
            raise RuntimeError('Final localization step has already been assessed')
        from ..schema import Snapshot
        from ..engine import evaluate_conditions
        snapshot = Snapshot.from_dict(deepcopy(self.snapshot_factory(self.agent, step))).as_dict()
        results = (self.evaluator or evaluate_conditions)(snapshot)
        selected = results[self.condition]
        if selected.get('condition') != self.condition:
            raise ValueError('Evaluator returned a different condition')
        self.apply_decision(step, deepcopy(selected))
        self.records.append({'phase': 'before_final_localization',
                             'condition': self.condition, 'results': deepcopy(results)})
        self._processed_step = step

    def on_step_start(self): pass
    def on_action_started(self, *, step): pass
    def on_action_executed(self, *, step): pass
    def on_step_done(self, *, step, info): pass
    def on_run_done(self, *, trajectory, info): pass
    def on_setup_attempt(self): pass
    def on_model_query(self, *, messages, agent): pass
    def on_query_message_added(self, **kwargs): pass
    def on_setup_done(self): pass
    def on_tools_installation_started(self): pass


def attach_pre_final_audit(agent, snapshot_factory: Callable, *, is_final_action: Callable,
                          apply_decision: Callable, condition: str = 'full_audit') -> PreFinalAuditHook:
    """Attach to the installed pinned SWE-agent; does not start the agent."""
    assert_installed_swe_agent_pin()
    verified_path('swe_agent', 'sweagent/agent/hooks/abstract.py')
    hook = PreFinalAuditHook(snapshot_factory, is_final_action=is_final_action,
                            apply_decision=apply_decision, condition=condition)
    agent.add_hook(hook)
    return hook
