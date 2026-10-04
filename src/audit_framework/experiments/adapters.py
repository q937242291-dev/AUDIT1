"""Actual execution adapters. No provider is constructed during planning/import.

The core adapter calls the shared deterministic engine. The pipeline adapter
invokes the built-in environment-configured HTTP provider (or an explicitly
supplied callback) and real read-only repository tools. Tests inject fixtures
instead of making network calls; constructing an adapter does not contact a provider.
"""
from __future__ import annotations
from copy import deepcopy
import importlib
import json
from pathlib import Path
import re
from .contracts import ProtocolError, digest, reject_outcomes, require, runtime_snapshot
from .methods import score_candidates, selected_paths, tool_anchor, trust_first
from .policies import audit_schedule


def import_symbol(spec: str):
    require(isinstance(spec, str) and ':' in spec, 'Adapter must be module:attribute')
    module, attribute = spec.rsplit(':', 1)
    value = getattr(importlib.import_module(module), attribute)
    require(callable(value), f'Adapter is not callable: {spec}')
    return value


class CoreAdapter:
    capabilities = frozenset({'component'})
    requires_model = False

    def __call__(self, snapshot: dict, condition: dict) -> dict:
        require(condition['pipeline'] == 'component', 'Core adapter only executes component conditions')
        from ..engine import evaluate
        return evaluate(runtime_snapshot(snapshot), condition['core_condition'])

    def evaluate_grid(self, snapshot: dict, conditions: list[dict]) -> dict:
        from ..engine import evaluate_conditions
        require(all(c['pipeline'] == 'component' for c in conditions), 'Mixed component grid')
        names = [c['core_condition'] for c in conditions]
        results = evaluate_conditions(runtime_snapshot(snapshot), names)
        # engine.evaluate_conditions computes all seven module outputs once.
        shared = None
        for result in results.values():
            require(len(result['all_module_outputs']) == 7, 'Incomplete shared module cache')
            value = digest(result['all_module_outputs'])
            require(shared is None or value == shared, 'Matched conditions changed module outputs')
            shared = value
        return {c['id']: deepcopy(results[c['core_condition']]) for c in conditions}


core_adapter = CoreAdapter()


def normalize_prediction(response: dict, snapshot: dict) -> list[dict]:
    require(isinstance(response, dict) and isinstance(response.get('files'), list), 'Model response must contain a files array')
    reject_outcomes(response, 'model_response')
    inventory = snapshot.get('repository_files')
    evidence = {e['id'] for e in snapshot.get('evidence', [])}
    files, seen = [], set()
    for item in response['files']:
        require(isinstance(item, dict), 'Prediction item must be an object')
        require(not set(item) - {'path', 'evidence_refs', 'score', 'rationale'}, 'Unregistered prediction field')
        path = item.get('path')
        require(isinstance(path, str) and path and not path.startswith('/') and ':' not in path
                and '\\' not in path and '..' not in path.split('/'), 'Invalid predicted repository path')
        require(path not in seen, 'Duplicate predicted path')
        require(inventory is None or path in inventory, f'Prediction outside repository inventory: {path}')
        refs = item.get('evidence_refs', [])
        require(isinstance(refs, list) and all(ref in evidence for ref in refs), 'Unknown prediction evidence reference')
        files.append({'path': path, 'evidence_refs': refs, 'score': item.get('score', 0),
                      'rationale': item.get('rationale', '')})
        seen.add(path)
    checked = {**deepcopy(snapshot), 'candidates': files}
    runtime_snapshot(checked)
    return files


class PipelineAdapter:
    capabilities = frozenset({'one_shot', 'tool_search', 'no_audit', 'full_audit',
                              'trust_first', 'policy', 'path_verifier', 'component'})
    requires_model = True

    def __init__(self, call_json=None):
        if call_json is None:
            from .http_provider import CompatibleHTTPProvider
            call_json = CompatibleHTTPProvider()
        self.call_json = call_json
        self.cache = {}
        self.ledger = []

    def configure(self, config: dict):
        if 'callback' in config:
            require(set(config) == {'callback'}, 'Callback cannot be combined with HTTP configuration')
            return type(self)(import_symbol(config['callback']))
        from .http_provider import CompatibleHTTPProvider
        return type(self)(CompatibleHTTPProvider(config))

    def _call(self, snapshot: dict, condition: dict, *, purpose: str, extra: dict | None = None) -> dict:
        require(callable(self.call_json), 'Execution requires a configured provider/harness JSON callback')
        runtime = condition['_runtime']
        require(runtime.get('model'), 'Execution model must be explicitly selected through its environment alias')
        payload = {'purpose': purpose, 'snapshot': runtime_snapshot(snapshot), **(extra or {})}
        reject_outcomes(payload, 'model_input')
        request = {'model': runtime['model'], 'system': runtime['prompt_template'],
                   'prompt': json.dumps(payload, ensure_ascii=False, sort_keys=True),
                   'purpose': purpose, 'reasoning_effort': condition.get('reasoning_effort'),
                   'parameters': deepcopy(runtime['parameters'])}
        response = self.call_json(deepcopy(request))
        require(isinstance(response, dict), 'Provider callback must return an object')
        parsed = response.get('parsed', response)
        require(isinstance(parsed, dict), 'Parsed provider response must be a JSON object')
        reject_outcomes(parsed, 'provider_response')
        self.ledger.append({'purpose': purpose, 'model': runtime['model'],
                            'request_sha256': digest(request), 'response_sha256': digest(parsed),
                            'usage': deepcopy(response.get('usage', {}))})
        return deepcopy(parsed)

    def _one_shot(self, snapshot: dict, condition: dict) -> dict:
        response = self._call(snapshot, condition, purpose='one_shot')
        return {'files': normalize_prediction(response, snapshot), 'snapshot': deepcopy(snapshot)}

    def _checkpoint(self, current: dict, condition: dict, *, stage: str,
                    index: int, evidence_changed: bool) -> tuple[dict, dict | None, dict | None]:
        """Decide against the current state, before any subsequent solver call."""
        schedule = audit_schedule(condition['policy'], stage=stage,
            evidence_changed=evidence_changed, checkpoint_index=index,
            interval=condition['_runtime']['parameters']['audit_interval'])
        if not schedule['audit']:
            return current, None, None
        prefix = runtime_snapshot(current)
        if condition['policy'] == 'online_generic_intervention':
            response = self._call(prefix, condition, purpose='online_generic_intervention',
                extra={'instruction': 'Review only the currently observed state. Return files and optional advice for the next tool step; do not assume unobserved evidence.'})
            require(isinstance(response.get('advice', ''), str), 'Generic intervention advice must be text')
            audited = {'files': normalize_prediction(response, prefix), 'advice': response.get('advice', '')}
        else:
            from ..engine import evaluate
            audited = evaluate(deepcopy(prefix), 'full_audit')
        record = {'checkpoint_index': index, 'schedule': schedule,
                  'snapshot': prefix, 'snapshot_sha256': digest(prefix), 'audit': deepcopy(audited)}
        feedback = None
        if schedule['intervene']:
            by_path = {c['path']: c for c in current.get('candidates', [])}
            if 'files' in audited:
                candidates = normalize_prediction(audited, current)
            else:
                decision = audited.get('decision', {})
                paths = selected_paths(audited) if decision.get('action') == 'select' else []
                require(all(path in by_path for path in paths), 'Audit introduced an unobserved candidate')
                candidates = [deepcopy(by_path[path]) for path in paths]
            current = deepcopy(current)
            current['candidates'] = candidates
            feedback = {'stage': stage, 'checkpoint_index': index,
                        'decision': deepcopy(audited.get('decision', {'ranking': selected_paths(audited)})),
                        'advice': audited.get('advice', ''),
                        'instruction': 'Use this current-state audit decision when choosing the next tool action or final localization.'}
        return current, record, feedback

    def _tool(self, snapshot: dict, condition: dict, *, policy: bool = False) -> dict:
        from .. import repository
        runtime = condition['_runtime']
        root = runtime.get('repository_root')
        require(root, 'Tool-search requires an explicit read-only repository_root binding')
        root = Path(root)
        current = runtime_snapshot(snapshot)
        current['repository_files'] = repository.inventory(root)
        current.setdefault('history', [])
        current.setdefault('evidence', [])
        current.setdefault('candidates', [])
        trace, observations = [], []
        feedback = None
        settings = runtime['parameters']
        for turn in range(settings['max_tool_turns']):
            extra = {'tool_trace': deepcopy(trace)}
            if feedback is not None:
                extra['audit_feedback'] = deepcopy(feedback)
            response = self._call(current, condition, purpose='tool_search', extra=extra)
            action = response.get('action', 'final')
            if action == 'final':
                files = normalize_prediction(response, current)
                changed = digest(files) != digest(current['candidates'])
                current['candidates'] = deepcopy(files)
                if policy:
                    current, record, _ = self._checkpoint(current, condition, stage='final',
                        index=turn, evidence_changed=changed)
                    if record is not None:
                        observations.append(record)
                return {'files': deepcopy(current['candidates']), 'snapshot': current,
                        'tool_trace': trace, 'audit_observations': observations,
                        'solver_files': files}
            require(action in {'list_tree', 'search_text', 'find_symbol', 'read_file'}, 'Unregistered tool action')
            # Intermediate proposals may cite only evidence already visible before this action.
            if 'files' in response:
                current['candidates'] = normalize_prediction(response, current)
            if action == 'list_tree':
                result = current['repository_files'][:settings['max_tool_matches']]
                observed = []
            elif action in {'search_text', 'find_symbol'}:
                query = response.get('query')
                require(isinstance(query, str) and query, 'Search action requires a literal query')
                result = repository.search(root, query, limit=settings['max_tool_matches'],
                                           max_chars=settings['max_tool_chars'])
                observed = list(dict.fromkeys(hit['path'] for hit in result))
            else:
                path = response.get('path')
                require(path in current['repository_files'], 'Read action outside repository inventory')
                result = repository.read_file(root, path, settings['max_tool_chars'])
                observed = [path]
            refs = []
            # Attach search hits to their own paths; never use the first hit as evidence
            # for other paths. Inventory discovery alone is not ownership evidence.
            for path in observed or [None]:
                content = ([hit for hit in result if hit['path'] == path]
                           if action in {'search_text', 'find_symbol'} and path else result)
                ref = 'tool_' + digest([current['task_id'], current.get('trial_id'), turn, action, path, content])[:20]
                refs.append(ref)
                current['evidence'].append({'id': ref, 'path': path, 'content': json.dumps(content, ensure_ascii=False),
                                            'kind': 'tool', 'tool_ref': ref})
                current['history'].append({'id': ref, 'task_id': current['task_id'],
                    'trial_id': current.get('trial_id', 'default'), 'action': action,
                    'object': path, 'candidate': path, 'evidence_ref': [ref]})
                if path is not None:
                    candidate = next((c for c in current['candidates'] if c['path'] == path), None)
                    if candidate is None:
                        candidate = {'path': path, 'score': 0, 'evidence_refs': [], 'rationale': 'Observed in current tool prefix'}
                        current['candidates'].append(candidate)
                    candidate.setdefault('evidence_refs', []).append(ref)
            trace.append({'action': action, 'path': observed[0] if len(observed) == 1 else None,
                          'result': result, 'evidence_refs': refs})
            runtime_snapshot(current)
            if policy:
                current, record, new_feedback = self._checkpoint(current, condition,
                    stage='checkpoint', index=turn, evidence_changed=bool(refs))
                if record is not None:
                    observations.append(record)
                if new_feedback is not None:
                    feedback = new_feedback
        # Exhausting the bound is not silently converted to a successful localization.
        raise ProtocolError('tool_search_turn_limit_without_final_prediction')

    def _shared_solver(self, snapshot: dict, condition: dict) -> dict:
        runtime = condition['_runtime']
        key = digest([snapshot, runtime['model'], runtime['parameters'], runtime['prompt_template'],
                      runtime.get('repository_state'), runtime.get('repository_root'), condition.get('reasoning_effort')])
        if key in self.cache:
            return deepcopy(self.cache[key])
        direct = self._one_shot(snapshot, condition)
        tool = self._tool(snapshot, condition)
        current = deepcopy(tool['snapshot'])
        evidence_by_path = {}
        for e in current.get('evidence', []):
            evidence_by_path.setdefault(e.get('path'), []).append(e)
        words = set(re.findall(r'[A-Za-z_][A-Za-z_0-9]{2,}', snapshot.get('issue', '').lower()))
        paths = set(selected_paths(direct)) | set(selected_paths(tool)) | {c['path'] for c in snapshot.get('candidates', [])}
        retrieval = [{'repo_relative': p, 'path_score': sum(w in p.lower() for w in words),
                      'content_hits': sum(e['content'].lower().count(w) for e in evidence_by_path.get(p, []) for w in words)}
                     for p in sorted(paths)]
        scored = score_candidates(retrieval, selected_paths(direct), selected_paths(tool), tool['tool_trace'])
        current['candidates'] = [{'path': r['candidate_file'], 'score': r['base_score'],
                                 'evidence_refs': [e['id'] for e in evidence_by_path.get(r['candidate_file'], [])]}
                                for r in scored]
        anchored = tool_anchor(scored, selected_paths(tool))
        bundle = {'one_shot': direct, 'tool_search': tool,
                  'no_audit': {'files': deepcopy(current['candidates']), 'fusion_features': scored},
                  'snapshot': current, 'anchored_ranking': [r['candidate_file'] for r in anchored],
                  'model_top1': selected_paths(tool)[0] if selected_paths(tool) else None}
        self.cache[key] = deepcopy(bundle)
        return bundle

    def _postprocess(self, bundle: dict, pipeline: str) -> dict:
        if pipeline in {'one_shot', 'tool_search', 'no_audit'}:
            return deepcopy(bundle[pipeline])
        from ..engine import evaluate
        audit = evaluate(deepcopy(bundle['snapshot']), 'full_audit')
        if pipeline == 'full_audit':
            return audit
        return trust_first(bundle['snapshot'], audit, bundle['anchored_ranking'], model_top1=bundle['model_top1'])

    def evaluate_methods(self, snapshot: dict, conditions: list[dict]) -> dict:
        require(bool(conditions), 'Empty method grid')
        fixed = [(c['_runtime']['model'], c['_runtime']['prompt_template'], c['_runtime']['parameters'],
                  c['_runtime'].get('repository_state'), c.get('reasoning_effort')) for c in conditions]
        require(all(value == fixed[0] for value in fixed), 'Matched methods changed fixed solver settings')
        start = len(self.ledger)
        bundle = self._shared_solver(runtime_snapshot(snapshot), conditions[0])
        output = {}
        for condition in conditions:
            result = self._postprocess(bundle, condition['pipeline'])
            result['execution'] = {'pipeline': condition['pipeline'], 'shared_solver_bundle_sha256': digest(bundle),
                                   'shared_provider_calls': len(self.ledger) - start,
                                   'call_records': deepcopy(self.ledger[start:])}
            output[condition['id']] = result
        return output

    def _policy(self, snapshot: dict, condition: dict) -> dict:
        result = self._tool(snapshot, condition, policy=True)
        result['policy'] = condition['policy']
        return result

    def _path_verifier(self, snapshot: dict, condition: dict) -> dict:
        response = self._call(snapshot, condition, purpose='path_verifier',
            extra={'instruction': 'Verify repository-visible candidate ownership and paths; return assessments [{path, verified, evidence_refs}].'})
        assessments = response.get('assessments')
        require(isinstance(assessments, list), 'Path verifier must return assessments')
        paths = {c['path'] for c in snapshot.get('candidates', [])}
        refs = {e['id'] for e in snapshot.get('evidence', [])}
        require(len(assessments) == len(paths) and {a.get('path') for a in assessments} == paths,
                'Path-verifier assessments must cover each candidate once')
        for item in assessments:
            require(set(item) <= {'path', 'verified', 'evidence_refs'}, 'Unregistered path-verifier field')
            require(type(item.get('verified')) is bool and isinstance(item.get('evidence_refs'), list), 'Invalid verifier assessment')
            require(all(r in refs for r in item['evidence_refs']), 'Verifier cites unavailable evidence')
            require(not item['verified'] or bool(item['evidence_refs']), 'Verified path requires cited evidence')
        return {'assessments': deepcopy(assessments),
                'files': [{'path': a['path']} for a in assessments if a['verified']]}

    def __call__(self, snapshot: dict, condition: dict) -> dict:
        snapshot = runtime_snapshot(snapshot)
        start = len(self.ledger)
        pipeline = condition['pipeline']
        require(pipeline in self.capabilities, f'Unsupported pipeline: {pipeline}')
        if pipeline == 'component':
            return core_adapter(snapshot, condition)
        if pipeline == 'one_shot': result = self._one_shot(snapshot, condition)
        elif pipeline == 'tool_search': result = self._tool(snapshot, condition)
        elif pipeline in {'no_audit', 'full_audit', 'trust_first'}:
            result = self._postprocess(self._shared_solver(snapshot, condition), pipeline)
        elif pipeline == 'policy': result = self._policy(snapshot, condition)
        else: result = self._path_verifier(snapshot, condition)
        result['execution'] = {'pipeline': pipeline, 'new_provider_calls': len(self.ledger) - start,
                               'call_records': deepcopy(self.ledger[start:])}
        return result

    def evaluate_grid(self, snapshot: dict, conditions: list[dict]) -> dict:
        return core_adapter.evaluate_grid(snapshot, conditions)


provider_adapter = PipelineAdapter()
