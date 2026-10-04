"""Bounded execution regressions: synthetic fixtures, network blocked, corpus read-only."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from audit_framework.experiments.adapters import PipelineAdapter, core_adapter, normalize_prediction
from audit_framework.experiments.catalog import CONFIG_ROOT, PACKAGE_ROOT, load_registry, registered_definitions
from audit_framework.experiments.contracts import ProtocolError, align_completed_pairs, digest, runtime_snapshot
from audit_framework.experiments.http_provider import CompatibleHTTPProvider, _NoRedirect
from audit_framework.experiments.methods import tool_anchor, trust_first
from audit_framework.experiments.planning import build_plan
from audit_framework.experiments.policies import audit_schedule
from audit_framework.experiments.runner import execute_plan


def fixture(empty=False):
    paths = ['src/a.py', 'src/b.py']
    value = {'task_id': 'synthetic_task', 'trial_id': 'synthetic_trial',
        'issue': 'Inspect source behavior', 'context': 'Repository-visible fixture only.',
        'candidates': [{'path': p, 'score': 1, 'evidence_refs': [p]} for p in paths],
        'evidence': [{'id': p, 'path': p, 'owner': p, 'content': 'def behavior(): return 1',
                      'tool_ref': 'read_' + p, 'claim': p, 'verified': True} for p in paths],
        'history': [{'id': 'step_' + p, 'action': 'read_file', 'object': p, 'candidate': p,
                     'evidence_ref': [p], 'verifier': {'status': 'pass', 'evidence_refs': [p],
                                                      'tool_ref': 'check_' + p}} for p in paths],
        'repository_files': paths, 'model_config': {'model': 'fixture_model'}}
    if empty:
        value.update(candidates=[], evidence=[], history=[])
    return value


def condition(pipeline, policy=None, turns=5):
    result = {'id': policy or pipeline, 'pipeline': pipeline, 'reasoning_effort': 'max',
        '_runtime': {'model': 'fixture_model', 'prompt_template': 'Return a JSON object.',
            'repository_root': 'fixture-repository', 'repository_state': 'fixed_fixture_state',
            'parameters': {'max_tool_turns': turns, 'max_tool_chars': 8000,
                           'max_tool_matches': 20, 'audit_interval': 1}}}
    if policy:
        result['policy'] = policy
    return result


def audit_result(snapshot, action='select'):
    paths = sorted(c['path'] for c in snapshot['candidates'])
    return {'decision': {'action': action, 'ranking': paths if action == 'select' else [],
                         'candidate': paths[0] if action == 'select' and paths else None},
            'module_outputs': {name: {'assessments': [{'candidate': p, 'verdict': 'pass'} for p in paths]}
                               for name in ('grounding', 'ownership', 'contradiction', 'detour',
                                            'path_verification', 'memory', 'abstention')}}


@contextmanager
def repository_fixture():
    with ExitStack() as stack:
        stack.enter_context(patch('audit_framework.repository.inventory', return_value=['src/a.py', 'src/b.py', 'src/future.py']))
        stack.enter_context(patch('audit_framework.repository.read_file',
            side_effect=lambda root, path, limit: {'path': path, 'content': 'Observed ' + path, 'truncated': False}))
        yield


def simple_tool_callback(request):
    snapshot = json.loads(request['prompt'])['snapshot']
    if not snapshot['history']:
        return {'action': 'read_file', 'path': 'src/a.py'}
    return {'action': 'final', 'files': deepcopy(snapshot['candidates'])}


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.guards = [patch.object(socket, 'create_connection', side_effect=AssertionError('Network forbidden in fixtures')),
                       patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden in fixtures'))]
        for guard in self.guards:
            guard.start()
            self.addCleanup(guard.stop)


class OnlinePolicyTests(OfflineTests):
    def test_audit_interleaves_before_next_tool_and_never_sees_future_candidates(self):
        events, requests, prefixes = [], [], []

        def provider(request):
            state = json.loads(request['prompt'])
            requests.append(deepcopy(state))
            events.append('solver')
            if len(requests) == 1:
                return {'action': 'read_file', 'path': 'src/a.py'}
            if len(requests) == 2:
                self.assertEqual(state['snapshot']['candidates'], [])
                self.assertEqual(state['audit_feedback']['decision']['action'], 'abstain')
                # The selected next action depends on the actual checkpoint decision.
                return {'action': 'read_file', 'path': 'src/b.py'}
            return {'action': 'final', 'files': deepcopy(state['snapshot']['candidates'])}

        def evaluate(snapshot, name):
            events.append('audit')
            prefixes.append(deepcopy(snapshot))
            return audit_result(snapshot, 'abstain' if len(prefixes) == 1 else 'select')

        initial = fixture(empty=True)
        before = deepcopy(initial)
        with repository_fixture(), patch('audit_framework.engine.evaluate', side_effect=evaluate):
            result = PipelineAdapter(provider)(initial, condition('policy', 'full_audit'))
        self.assertEqual(events, ['solver', 'audit', 'solver', 'audit', 'solver', 'audit'])
        self.assertEqual([c['path'] for c in prefixes[0]['candidates']], ['src/a.py'])
        self.assertEqual([e['path'] for e in prefixes[0]['evidence']], ['src/a.py'])
        self.assertNotIn('src/b.py', [h.get('candidate') for h in prefixes[0]['history']])
        self.assertEqual(len(prefixes[0]['history']), 1)
        self.assertEqual(len(prefixes[1]['history']), 2)
        self.assertEqual([c['path'] for c in result['files']], ['src/b.py'])
        for observation in result['audit_observations']:
            current = observation['snapshot']
            refs = {e['id'] for e in current['evidence']}
            self.assertTrue(all(set(c['evidence_refs']) <= refs for c in current['candidates']))
            self.assertNotIn('src/future.py', [c['path'] for c in current['candidates']])
        self.assertEqual(initial, before)

    def test_observe_only_does_not_change_next_request_or_final_files(self):
        def run(policy):
            prompts = []
            def provider(request):
                prompts.append(json.loads(request['prompt']))
                return simple_tool_callback(request)
            with repository_fixture(), patch('audit_framework.engine.evaluate',
                    side_effect=lambda snapshot, name: audit_result(snapshot, 'abstain')) as audit:
                result = PipelineAdapter(provider)(fixture(empty=True), condition('policy', policy))
            return prompts, result, audit.call_count
        baseline, solver, count = run('solver_only')
        observed, observer, observed_count = run('observe_only_audit')
        self.assertEqual(count, 0)
        self.assertEqual(observed_count, 2)
        self.assertEqual(baseline, observed)
        self.assertEqual(solver['files'], observer['files'])
        self.assertEqual(len(observer['audit_observations']), 2)

    def test_end_of_run_audit_has_no_checkpoint_intervention(self):
        order = []
        def provider(request):
            order.append('solver')
            self.assertNotIn('audit_feedback', json.loads(request['prompt']))
            return simple_tool_callback(request)
        def evaluate(snapshot, name):
            order.append('audit')
            return audit_result(snapshot, 'abstain')
        with repository_fixture(), patch('audit_framework.engine.evaluate', side_effect=evaluate):
            result = PipelineAdapter(provider)(fixture(empty=True), condition('policy', 'end_of_run_audit'))
        self.assertEqual(order, ['solver', 'solver', 'audit'])
        self.assertEqual(result['files'], [])

    def test_evidence_grounded_policy_is_online(self):
        seen = []
        def provider(request):
            state = json.loads(request['prompt'])
            seen.append(state)
            if len(seen) == 1:
                return {'action': 'read_file', 'path': 'src/a.py'}
            self.assertIn('audit_feedback', state)
            return {'action': 'final', 'files': state['snapshot']['candidates']}
        with repository_fixture(), patch('audit_framework.engine.evaluate',
                side_effect=lambda snapshot, name: audit_result(snapshot)) as audit:
            PipelineAdapter(provider)(fixture(empty=True), condition('policy', 'evidence_grounded_intervention'))
        self.assertGreaterEqual(audit.call_count, 1)

    def test_generic_online_intervention_uses_provider_and_not_core(self):
        purposes = []
        def provider(request):
            state = json.loads(request['prompt'])
            purposes.append(request['purpose'])
            if request['purpose'] == 'online_generic_intervention':
                return {'files': state['snapshot']['candidates'], 'advice': 'Inspect current owner before finalizing.'}
            if not state['snapshot']['history']:
                return {'action': 'read_file', 'path': 'src/a.py'}
            self.assertEqual(state['audit_feedback']['advice'], 'Inspect current owner before finalizing.')
            return {'action': 'final', 'files': state['snapshot']['candidates']}
        with repository_fixture(), patch('audit_framework.engine.evaluate', side_effect=AssertionError('No typed audit here')):
            PipelineAdapter(provider)(fixture(empty=True), condition('policy', 'online_generic_intervention'))
        self.assertEqual(purposes, ['tool_search', 'online_generic_intervention', 'tool_search', 'online_generic_intervention'])

    def test_future_reference_cannot_enter_intermediate_proposal(self):
        response = {'action': 'read_file', 'path': 'src/a.py',
                    'files': [{'path': 'src/a.py', 'evidence_refs': ['not_observed_yet']}]}
        with repository_fixture(), patch('audit_framework.engine.evaluate') as audit:
            with self.assertRaisesRegex(ProtocolError, 'Unknown prediction evidence'):
                PipelineAdapter(lambda request: response)(fixture(empty=True), condition('policy', 'full_audit'))
        audit.assert_not_called()

    def test_turn_limit_does_not_fabricate_completed_prediction(self):
        with repository_fixture(), self.assertRaisesRegex(ProtocolError, 'turn_limit'):
            PipelineAdapter(lambda request: {'action': 'read_file', 'path': 'src/a.py'})(
                fixture(empty=True), condition('tool_search', turns=1))

    def test_scheduler_interval_and_six_registered_policies(self):
        policies = registered_definitions()['experiments']['audit_policy']['conditions']
        self.assertEqual(len(policies), 6)
        self.assertFalse(audit_schedule('full_audit', stage='checkpoint', checkpoint_index=1, interval=2)['audit'])
        self.assertTrue(audit_schedule('full_audit', stage='checkpoint', checkpoint_index=2, interval=2)['intervene'])
        self.assertFalse(audit_schedule('evidence_grounded_intervention', stage='checkpoint')['audit'])
        self.assertFalse(audit_schedule('solver_only', stage='final')['audit'])

    def test_tool_search_calls_actual_read_only_repository_functions(self):
        path = Path(__file__).name
        def provider(request):
            snapshot = json.loads(request['prompt'])['snapshot']
            if not snapshot['history']:
                return {'action': 'read_file', 'path': path}
            self.assertIn('Bounded execution regressions', snapshot['evidence'][0]['content'])
            return {'action': 'final', 'files': snapshot['candidates']}
        spec = condition('tool_search')
        spec['_runtime']['repository_root'] = str(Path(__file__).parent)
        result = PipelineAdapter(provider)(fixture(empty=True), spec)
        self.assertEqual(result['files'][0]['path'], path)
        self.assertEqual(result['execution']['new_provider_calls'], 2)


class MethodIsolationTests(OfflineTests):
    def test_no_audit_never_calls_core_and_auditing_is_lazy_after_cache_hit(self):
        calls = []
        def provider(request):
            calls.append(request['purpose'])
            snapshot = json.loads(request['prompt'])['snapshot']
            return {'files': list(reversed(snapshot['candidates']))}
        adapter = PipelineAdapter(provider)
        with repository_fixture(), patch('audit_framework.engine.evaluate', side_effect=AssertionError('no_audit must not audit')):
            result = adapter(fixture(), condition('no_audit'))
            cached = adapter(fixture(), condition('no_audit'))
        self.assertEqual(calls, ['one_shot', 'tool_search'])
        self.assertIn('fusion_features', result)
        self.assertNotIn('audit', result)
        self.assertEqual(cached['execution']['new_provider_calls'], 0)
        with patch('audit_framework.engine.evaluate', side_effect=lambda s, c: audit_result(s)) as audit:
            audited = adapter(fixture(), condition('full_audit'))
        audit.assert_called_once()
        self.assertIn('decision', audited)
        self.assertEqual(len(calls), 2)

    def test_trust_anchor_changes_selected_ranking_without_controller_reranking(self):
        snapshot = fixture()
        audited = audit_result(snapshot)
        self.assertEqual(audited['decision']['ranking'], ['src/a.py', 'src/b.py'])
        forward = trust_first(snapshot, audited, ['src/a.py', 'src/b.py'])
        backward = trust_first(snapshot, audited, ['src/b.py', 'src/a.py'])
        self.assertEqual(forward['files'][0]['path'], 'src/a.py')
        self.assertEqual(backward['files'][0]['path'], 'src/b.py')
        self.assertEqual([f['path'] for f in backward['files']], ['src/b.py', 'src/a.py'])

    def test_adapter_passes_anchor_to_gate(self):
        def provider(request):
            state = json.loads(request['prompt'])['snapshot']
            return {'files': list(reversed(state['candidates']))}
        with repository_fixture(), patch('audit_framework.engine.evaluate', side_effect=lambda s, c: audit_result(s)):
            result = PipelineAdapter(provider)(fixture(), condition('trust_first'))
        self.assertEqual(result['retained_candidates'], ['src/b.py', 'src/a.py'])
        self.assertEqual(result['files'][0]['path'], 'src/b.py')

    def test_trust_anchor_does_not_resurrect_failed_candidate(self):
        snapshot = fixture()
        audited = audit_result(snapshot)
        audited['module_outputs']['path_verification']['assessments'][1]['verdict'] = 'fail'
        result = trust_first(snapshot, audited, ['src/b.py', 'src/a.py'])
        self.assertEqual(result['files'], [])
        self.assertTrue(result['abstained'])
        self.assertFalse(result['process_valid'])
        self.assertEqual(result['retained_candidates'], ['src/b.py', 'src/a.py'])
        self.assertFalse(result['process_checks']['src/b.py']['valid'])
        audited['decision']['ranking'] = []
        self.assertTrue(trust_first(snapshot, audited, ['src/b.py', 'src/a.py'])['abstained'])

    def test_real_engine_gate_keeps_anchor_for_valid_candidates(self):
        from audit_framework.engine import evaluate
        snapshot = fixture()
        audited = evaluate(snapshot, 'full_audit')
        result = trust_first(snapshot, audited, ['src/b.py', 'src/a.py'])
        self.assertEqual([c['path'] for c in result['files']], ['src/b.py', 'src/a.py'])

    def test_shared_method_grid_generates_once_and_keeps_five_distinct_outputs(self):
        calls = []
        def provider(request):
            calls.append(request['purpose'])
            current = json.loads(request['prompt'])['snapshot']
            files = current['candidates'] if request['purpose'] == 'one_shot' else list(reversed(current['candidates']))
            return {'files': files}
        conditions = [condition(name) for name in ('one_shot', 'tool_search', 'no_audit', 'full_audit', 'trust_first')]
        with repository_fixture(), patch('audit_framework.engine.evaluate', side_effect=lambda s, c: audit_result(s)) as audit:
            results = PipelineAdapter(provider).evaluate_methods(fixture(), conditions)
        self.assertEqual(calls, ['one_shot', 'tool_search'])
        self.assertEqual(audit.call_count, 2)
        self.assertEqual(results['one_shot']['files'][0]['path'], 'src/a.py')
        self.assertEqual(results['tool_search']['files'][0]['path'], 'src/b.py')
        self.assertIn('fusion_features', results['no_audit'])
        self.assertIn('decision', results['full_audit'])
        self.assertTrue(results['trust_first']['process_valid'])

    def test_boundary_rejects_nested_outcome_and_unknown_or_nonportable_refs(self):
        bad = fixture()
        bad['evidence'][0]['gold_files'] = ['src/a.py']
        with self.assertRaises(ValueError):
            runtime_snapshot(bad)
        for path, refs in [('src/a.py', ['future_ref']), ('src\\a.py', [])]:
            with self.subTest(path=path), self.assertRaises(ProtocolError):
                normalize_prediction({'files': [{'path': path, 'evidence_refs': refs}]}, fixture())


class HTTPProviderTests(OfflineTests):
    def request(self):
        return {'model': 'fixture_model', 'system': 'Fixed template', 'prompt': '{"snapshot":{}}',
                'reasoning_effort': 'max'}

    def response(self, content='{"files":[]}', finish='stop'):
        response = io.BytesIO(json.dumps({'choices': [{'finish_reason': finish,
            'message': {'content': content}}], 'usage': {'total_tokens': 12}}).encode())
        response.status = 200
        return response

    def test_builtin_adapter_is_available_without_custom_callback_or_network(self):
        with patch('audit_framework.experiments.http_provider.build_opener') as transport:
            self.assertIsInstance(PipelineAdapter().call_json, CompatibleHTTPProvider)
            self.assertIsInstance(PipelineAdapter().configure({}).call_json, CompatibleHTTPProvider)
        transport.assert_not_called()

    def test_http_wire_contract_and_pipeline_dispatch_with_mocked_transport(self):
        opener = Mock()
        opener.open.return_value = self.response()
        with patch.dict(os.environ, {'AUDIT_HTTP_ENDPOINT': 'https://fixture.invalid/v1/chat/completions',
                                     'AUDIT_API_KEY': 'fixture-secret'}, clear=True), \
             patch('audit_framework.experiments.http_provider.build_opener', return_value=opener):
            result = PipelineAdapter()(fixture(), condition('one_shot'))
        request = opener.open.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.method, 'POST')
        self.assertEqual(request.get_header('Authorization'), 'Bearer fixture-secret')
        self.assertEqual(body['model'], 'fixture_model')
        self.assertEqual(body['messages'][0]['content'], 'Return a JSON object.')
        self.assertEqual(body['response_format'], {'type': 'json_object'})
        self.assertEqual(json.loads(body['messages'][1]['content'])['purpose'], 'one_shot')
        self.assertEqual(body['reasoning_effort'], 'max')
        self.assertEqual(result['files'], [])
        self.assertEqual(result['execution']['new_provider_calls'], 1)
        self.assertNotIn('fixture-secret', json.dumps(result))
        opener.open.assert_called_once()

    def test_optional_reasoning_parameter_is_explicit(self):
        opener = Mock()
        opener.open.return_value = self.response()
        with patch.dict(os.environ, {'AUDIT_HTTP_ENDPOINT': 'http://127.0.0.1:8888/chat'}, clear=True), \
             patch('audit_framework.experiments.http_provider.build_opener', return_value=opener):
            CompatibleHTTPProvider({'send_reasoning_effort': True, 'max_tokens': 400})(self.request())
        body = json.loads(opener.open.call_args.args[0].data)
        self.assertEqual(body['reasoning_effort'], 'max')
        self.assertEqual(body['max_tokens'], 400)

    def test_disabling_declared_reasoning_effort_fails_before_transport(self):
        with patch('audit_framework.experiments.http_provider.build_opener') as transport:
            with self.assertRaisesRegex(ProtocolError, 'reasoning_effort cannot be disabled'):
                CompatibleHTTPProvider({'send_reasoning_effort': False})(self.request())
        transport.assert_not_called()

    def test_missing_configuration_or_insecure_remote_endpoint_fails_before_network(self):
        for environment in ({}, {'AUDIT_HTTP_ENDPOINT': 'http://fixture.invalid/chat'},
                            {'AUDIT_HTTP_ENDPOINT': 'https://fixture.invalid/chat'},
                            {'AUDIT_HTTP_ENDPOINT': 'https://user:secret@fixture.invalid/chat', 'AUDIT_API_KEY': 'x'}):
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True), \
                 patch('audit_framework.experiments.http_provider.build_opener') as transport:
                with self.assertRaises(ProtocolError):
                    CompatibleHTTPProvider()(self.request())
                transport.assert_not_called()

    def test_http_error_is_sanitized_and_never_retried(self):
        opener = Mock()
        opener.open.side_effect = HTTPError('https://fixture.invalid', 401, 'sensitive-body', {}, None)
        with patch.dict(os.environ, {'AUDIT_HTTP_ENDPOINT': 'http://localhost/chat'}, clear=True), \
             patch('audit_framework.experiments.http_provider.build_opener', return_value=opener):
            with self.assertRaisesRegex(ProtocolError, '^Provider HTTP status 401; no automatic retry$'):
                CompatibleHTTPProvider()(self.request())
        opener.open.assert_called_once()

    def test_invalid_truncated_or_oversized_provider_results_fail_closed(self):
        cases = [('not-json', 'stop', {}), ('[]', 'stop', {}), ('{"files":[]}', 'length', {}),
                 ('{"files":[]}', 'stop', {'max_response_bytes': 8})]
        for content, finish, config in cases:
            opener = Mock()
            opener.open.return_value = self.response(content, finish)
            with self.subTest(content=content, finish=finish, config=config), \
                 patch.dict(os.environ, {'AUDIT_HTTP_ENDPOINT': 'http://localhost/chat'}, clear=True), \
                 patch('audit_framework.experiments.http_provider.build_opener', return_value=opener), \
                 self.assertRaises(ProtocolError):
                CompatibleHTTPProvider(config)(self.request())

    def test_redirects_cannot_forward_credentials(self):
        with self.assertRaisesRegex(ProtocolError, 'redirects are disabled'):
            _NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid')


class PlanningContractTests(OfflineTests):
    def setUp(self):
        super().setUp()
        from audit_framework.experiments.cohorts import seal_registration
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.task_list_root = Path(directory.name)
        units = [{'instance_id': f'fixture_task_{n:03d}', 'repo': 'fixture_repo', 'base_commit': 'fixture_commit'} for n in range(60)]
        registration = seal_registration('component_ablation', units, source='synthetic_test_fixture')
        (self.task_list_root/'component_ablation.json').write_text(json.dumps(registration))

    def test_public_registry_is_current_and_runtime_methods_are_canonical(self):
        registry = load_registry()
        self.assertEqual(registry, registered_definitions())
        methods = registry['experiments']['localization_methods']['conditions']
        self.assertEqual([c['id'] for c in methods], ['one_shot', 'tool_search', 'no_audit', 'full_audit', 'trust_first'])
        self.assertTrue(all('paper_label' in c for c in methods))
        for condition_ in methods:
            self.assertFalse(condition_['id'].startswith('shenji_'))

    def test_registered_sixty_task_grid_and_plan_are_provider_free(self):
        data_root = PACKAGE_ROOT / 'data'
        if not data_root.is_dir():
            data_root = PACKAGE_ROOT.parent / 'audit_anonymous_submission' / 'data'
        with patch('audit_framework.experiments.http_provider.build_opener', side_effect=AssertionError('Planning cannot construct transport')):
            plan = build_plan('component_ablation', task_list_root=self.task_list_root)
        self.assertEqual(plan['planned_jobs'], 540)
        self.assertEqual(len({j['instance_id'] for j in plan['jobs']}), 60)
        self.assertEqual(plan['provider_calls'], 0)
        self.assertEqual(len({j['prompt_template_sha256'] for j in plan['jobs']}), 1)
        task_list = json.loads((self.task_list_root / 'component_ablation.json').read_text(encoding='utf-8'))
        self.assertEqual(set(task_list['task_ids']), {j['instance_id'] for j in plan['jobs']})

    def component_execution(self):
        data_root = PACKAGE_ROOT / 'data'
        if not data_root.is_dir():
            data_root = PACKAGE_ROOT.parent / 'audit_anonymous_submission' / 'data'
        plan = build_plan('component_ablation', task_list_root=self.task_list_root, limit_units=1)
        job = plan['jobs'][0]
        snapshot = fixture()
        snapshot.update(task_id=job['instance_id'], trial_id=job['unit_id'])
        unit = job['unit']
        repository = {'repo': unit.get('repo', unit.get('repository', 'fixture_repo')),
                      'base_commit': unit.get('base_commit', 'fixture_commit'), 'state_hash': 'fixture_state'}
        envelope = {'cohort': job['cohort'], 'unit_id': job['unit_id'], 'snapshot': snapshot, 'repository': repository}
        return plan, {(job['cohort'], job['unit_id']): envelope}

    def test_component_execution_computes_once_and_preserves_cached_module_outputs(self):
        from audit_framework.modules import run_modules
        plan, inputs = self.component_execution()
        with patch('audit_framework.engine.run_modules', wraps=run_modules) as modules:
            result = execute_plan(plan, inputs, execute=True, environment={})
        modules.assert_called_once()
        self.assertEqual((result['scheduled_n'], result['completed_n'], result['noncompleted_n']), (9, 9, 0))
        self.assertEqual(len({digest(r['result']['all_module_outputs']) for r in result['rows']}), 1)
        self.assertEqual(len(result['component_caches']), 1)
        paired = align_completed_pairs(result['rows'], 'full_audit', 'minus_grounding')
        self.assertEqual((paired['scheduled_n'], paired['completed_pair_n']), (1, 1))

    def test_pair_accounting_rejects_missing_duplicate_and_changed_fixed_rows(self):
        plan, inputs = self.component_execution()
        result = execute_plan(plan, inputs, execute=True, environment={})
        rows = [deepcopy(r) for r in result['rows'] if r['condition_id'] in {'full_audit', 'minus_grounding'}]
        rows[1]['status'] = 'incomplete'
        aligned = align_completed_pairs(rows, 'full_audit', 'minus_grounding')
        self.assertEqual((aligned['scheduled_n'], aligned['completed_pair_n'], aligned['excluded_n']), (1, 0, 1))
        for bad in (rows[:1], rows + [rows[0]], [rows[0], {**rows[1], 'base_commit': 'changed'}]):
            with self.assertRaises(ProtocolError):
                align_completed_pairs(bad, 'full_audit', 'minus_grounding')

    def test_execution_requires_explicit_opt_in_and_registered_identity(self):
        plan, inputs = self.component_execution()
        with self.assertRaisesRegex(ProtocolError, 'opt-in'):
            execute_plan(plan, inputs)
        inputs[next(iter(inputs))]['snapshot']['task_id'] = 'unregistered_task'
        with self.assertRaisesRegex(ProtocolError, 'Runtime task differs'):
            execute_plan(plan, inputs, execute=True, environment={})


if __name__ == '__main__':
    unittest.main()
