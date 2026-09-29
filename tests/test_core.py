"""Pure synthetic method tests. No providers, empirical inputs or result writes.

Run: python -B -m unittest discover -s tests -p test_core.py -v
with src on PYTHONPATH. Fixtures assert behavior, not empirical paper outcomes.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from audit_framework import (BoundaryError, MODULE_NAMES, Snapshot, available_conditions,
                             evaluate, evaluate_conditions)
from audit_framework.conditions import load_condition
from audit_framework.controllers import aggregate, majority_controller
from audit_framework.memory import EvidenceMemory
from audit_framework.modules import repository_path_status, run_modules
from audit_framework.schema import Assessment, ModuleOutput, ModuleProvenance


def fixture() -> dict:
    return {
        'task_id': 'synthetic_task', 'trial_id': 'trial_one', 'issue': 'Inspect source behavior',
        'context': 'Synthetic agent-visible source only.',
        'candidates': [{'path': 'src/a.py', 'evidence_refs': ['a'], 'score': 1},
                       {'path': 'src/b.py', 'evidence_refs': ['b'], 'score': 99}],
        'evidence': [
            {'id': 'a', 'path': 'src/a.py', 'owner': 'src/a.py', 'content': 'def a(): return 1',
             'tool_ref': 'read_a', 'claim': 'behavior_a', 'verified': True},
            {'id': 'b', 'path': 'src/b.py', 'owner': 'src/b.py', 'content': 'def b(): return 2',
             'tool_ref': 'read_b', 'claim': 'behavior_b', 'verified': True},
        ],
        'history': [
            {'id': 'step_a', 'context': 'inspect a', 'action': 'read_file', 'object': 'src/a.py',
             'candidate': 'src/a.py', 'evidence_ref': ['a'],
             'verifier': {'status': 'pass', 'evidence_refs': ['a'], 'tool_ref': 'check_a'},
             'resource': {'tokens': 100, 'calls': 1}},
            {'id': 'step_b', 'context': 'inspect b', 'action': 'read_file', 'object': 'src/b.py',
             'candidate': 'src/b.py', 'evidence_ref': ['b'],
             'verifier': {'status': 'pass', 'evidence_refs': ['b'], 'tool_ref': 'check_b'},
             'resource': {'tokens': 200, 'calls': 1}},
        ],
        'repository_files': ['src/a.py', 'src/b.py'],
        'model_config': {'model': 'fixture_model', 'reasoning_effort': 'max', 'seed': 1},
    }


def synthetic_outputs() -> tuple[ModuleOutput, ...]:
    provenance = ModuleProvenance('fixture', 'fixture_snapshot', 'fixture_parameters', ())
    assessments = tuple(Assessment(path, 'pass', 1.0, ('fixture',)) for path in ('src/a.py', 'src/b.py'))
    return tuple(ModuleOutput(name, assessments, 'src/a.py', False, provenance) for name in MODULE_NAMES)


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.network_guards = [
            patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden')),
            patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')),
        ]
        for guard in cls.network_guards:
            guard.start()

    @classmethod
    def tearDownClass(cls):
        for guard in reversed(cls.network_guards):
            guard.stop()

    def test_nine_registered_conditions_hold_all_parameters_fixed(self):
        names = available_conditions()
        self.assertEqual(len(names), 9)
        full = load_condition('full_audit')
        for name in names:
            with self.subTest(name=name):
                config = load_condition(name)
                self.assertEqual(config.module_parameters, full.module_parameters)
                self.assertEqual(config.controller_parameters, full.controller_parameters)
                self.assertEqual(config.quality_parameters, full.quality_parameters)
                expected = tuple(m for m in MODULE_NAMES if name != f'minus_{m}')
                self.assertEqual(config.enabled_modules, expected)
                self.assertEqual(config.controller, 'majority' if name == 'majority_controller' else 'full')
        names.clear()
        self.assertEqual(len(available_conditions()), 9)

    def test_matrix_runs_modules_once_and_reuses_exact_immutable_objects(self):
        seen = []
        def capture(candidates, outputs, controller, params):
            seen.append(outputs)
            return aggregate(candidates, outputs, controller, params)
        with patch('audit_framework.engine.run_modules', wraps=run_modules) as compute:
            with patch('audit_framework.engine.aggregate', side_effect=capture):
                results = evaluate_conditions(fixture())
        compute.assert_called_once()
        self.assertEqual(len(seen), 9)
        original_objects = {output.module: output for output in seen[0]}
        for outputs in seen:
            for output in outputs:
                self.assertIs(output, original_objects[output.module])
        baseline = results['full_audit']
        for name, result in results.items():
            self.assertEqual(result['all_module_outputs'], baseline['all_module_outputs'])
            self.assertEqual(result['module_outputs_digest'], baseline['module_outputs_digest'])
            self.assertEqual(result['snapshot_digest'], baseline['snapshot_digest'])
            self.assertEqual(result['quality'], baseline['quality'])
            self.assertEqual(result['trace'], baseline['trace'])
            self.assertEqual(set(result['module_outputs']), set(result['enabled_modules']))
            self.assertEqual(len(result['disabled_modules']), int(name.startswith('minus_')))
        results['minus_memory']['all_module_outputs']['grounding']['vote'] = 'mutated'
        self.assertNotEqual(baseline['all_module_outputs']['grounding']['vote'], 'mutated')

    def test_each_disabled_output_has_no_effect_with_enabled_positive_controls(self):
        initial = synthetic_outputs()
        for removed in MODULE_NAMES:
            with self.subTest(removed=removed):
                changed = tuple(replace(output,
                    assessments=(Assessment('src/a.py', 'fail', 0.0, ('injected_failure',)),
                                 Assessment('src/b.py', 'pass', 1.0, ('alternative',))),
                    vote='src/b.py') if output.module == removed else output for output in initial)
                with patch('audit_framework.engine.run_modules', return_value=initial):
                    base = evaluate(fixture(), f'minus_{removed}')
                    positive_before = evaluate(fixture(), 'full_audit')
                with patch('audit_framework.engine.run_modules', return_value=changed):
                    altered = evaluate(fixture(), f'minus_{removed}')
                    positive_after = evaluate(fixture(), 'full_audit')
                self.assertEqual(base['decision'], altered['decision'])
                self.assertEqual(base['module_outputs'], altered['module_outputs'])
                self.assertEqual(base['quality'], altered['quality'])
                self.assertEqual(positive_before['decision']['candidate'], 'src/a.py')
                self.assertEqual(positive_after['decision']['candidate'], 'src/b.py')

    def test_majority_retains_outputs_and_never_calls_full_controller(self):
        expected = evaluate(fixture())['all_module_outputs']
        with patch('audit_framework.controllers.full_controller', side_effect=AssertionError('wrong controller')):
            result = evaluate(fixture(), 'majority_controller')
        self.assertEqual(result['all_module_outputs'], expected)
        self.assertEqual(result['module_outputs'], expected)
        self.assertEqual(result['disabled_modules'], [])
        self.assertEqual(result['decision']['votes_cast'], 7)

    def test_majority_counts_module_votes_not_candidate_prior_or_track_support(self):
        outputs = tuple(replace(output, vote='src/b.py') if index < 4 else output
                        for index, output in enumerate(synthetic_outputs()))
        result = majority_controller(('src/a.py', 'src/b.py'), outputs,
                                     load_condition('majority').controller_parameters)
        self.assertEqual(result['candidate'], 'src/b.py')
        self.assertEqual(result['vote_counts'], {'src/a.py': 3, 'src/b.py': 4})
        self.assertEqual(result['winner_votes'], 4)
        self.assertTrue(result['strict_majority'])
        self.assertEqual({ballot['module'] for ballot in result['ballots']}, set(MODULE_NAMES))

    def test_majority_stable_tie_neutral_votes_and_abstention_ballot(self):
        initial = synthetic_outputs()
        outputs = (initial[0], replace(initial[1], vote='src/b.py'),
                   replace(initial[2], vote=None))
        params = load_condition('majority').controller_parameters
        result = majority_controller(('src/b.py', 'src/a.py'), outputs, params)
        self.assertEqual(result['candidate'], 'src/a.py')
        self.assertEqual(result['votes_cast'], 2)
        self.assertFalse(result['strict_majority'])
        abstention = replace(initial[-1], vote=None, abstain=True)
        tied = majority_controller(('src/a.py', 'src/b.py'), (initial[0], abstention), params)
        self.assertEqual(tied['action'], 'abstain')
        self.assertEqual(tied['abstain_votes'], 1)
        none = majority_controller(('src/a.py', 'src/b.py'), (), params)
        self.assertEqual(none['action'], 'no_votes')
        self.assertIsNone(none['candidate'])

    def test_grounding_rejects_unresolved_and_empty_sources(self):
        for bad_ref in ('missing', 'empty'):
            with self.subTest(ref=bad_ref):
                raw = fixture()
                raw['candidates'][0]['evidence_refs'].append(bad_ref)
                raw['evidence'].append({'id': 'empty', 'path': 'src/a.py', 'owner': 'src/a.py'})
                full = evaluate(raw)
                removed = evaluate(raw, 'minus_grounding')
                self.assertEqual(full['module_outputs']['grounding']['assessments'][0]['verdict'], 'fail')
                self.assertEqual(full['decision']['candidate'], 'src/b.py')
                self.assertEqual(removed['decision']['candidate'], 'src/a.py')
                self.assertEqual(full['all_module_outputs']['ownership'], removed['module_outputs']['ownership'])

    def test_ownership_uses_source_owner_and_removal_changes_only_that_output(self):
        raw = fixture()
        raw['evidence'][0]['owner'] = 'src/b.py'
        full = evaluate(raw)
        removed = evaluate(raw, 'minus_ownership')
        self.assertEqual(full['decision']['candidate'], 'src/b.py')
        # Grounding, path and contradiction still pass; changed source ownership
        # also affects fixed memory scores, but never reads the ownership output.
        self.assertNotIn('ownership', removed['module_outputs'])
        for module in set(MODULE_NAMES) - {'ownership'}:
            self.assertEqual(full['all_module_outputs'][module], removed['module_outputs'][module])

    def test_contradiction_blocks_opposed_claim_and_can_be_removed(self):
        raw = fixture()
        raw['history'] = []
        raw['evidence'].append({'id': 'opposition', 'path': 'src/a.py', 'owner': 'src/a.py',
                                'content': 'observed counterexample', 'claim': 'behavior_a',
                                'polarity': 'oppose', 'contradicts': ['a']})
        full = evaluate(raw)
        removed = evaluate(raw, 'minus_contradiction')
        self.assertEqual(full['decision']['candidate'], 'src/b.py')
        self.assertEqual(removed['decision']['candidate'], 'src/a.py')
        self.assertIn('opposition', full['module_outputs']['contradiction']['assessments'][0]['evidence_refs'])

    def test_detour_detects_repeated_exploration_without_new_evidence(self):
        raw = fixture()
        raw['history'].extend([{**raw['history'][0], 'id': 'repeat_one'},
                               {**raw['history'][0], 'id': 'repeat_two'}])
        full = evaluate(raw)
        self.assertEqual(full['module_outputs']['detour']['assessments'][0]['verdict'], 'fail')
        self.assertEqual(full['decision']['candidate'], 'src/b.py')
        self.assertEqual(evaluate(raw, 'minus_detour')['decision']['candidate'], 'src/a.py')

    def test_invalid_paths_cannot_pass_by_appearing_in_inventory(self):
        invalid = ('../secret.py', '/tmp/file.py', 'C:/local/file.py', 'a\\b.py',
                   'a//b.py', './a.py', 'a/../b.py', 'a/./b.py', 'a.py/', 'a\x00.py')
        for path in invalid:
            with self.subTest(path=path):
                self.assertEqual(repository_path_status(path, (path,))[0], 'fail')
                raw = {'task_id': 'path_fixture', 'repository_files': [path],
                       'candidates': [{'path': path, 'evidence_refs': ['e']}],
                       'evidence': [{'id': 'e', 'path': path, 'content': 'source'}]}
                full = evaluate(raw)
                self.assertEqual(full['decision']['action'], 'blocked')
                self.assertEqual(evaluate(raw, 'minus_path_verification')['decision']['candidate'], path)

    def test_inventory_absent_empty_and_valid_paths_are_distinct(self):
        for path in ('a' + chr(92) + 'b.py', 'a' + chr(0) + '.py'):
            self.assertEqual(repository_path_status(path, (path,))[0], 'fail')
        self.assertEqual(repository_path_status('src/a.py', None)[0], 'unknown')
        self.assertEqual(repository_path_status('src/a.py', ())[0], 'fail')
        self.assertEqual(repository_path_status('src/a.py', ('src/a.py',))[0], 'pass')
        self.assertEqual(repository_path_status('SRC/a.py', ('src/a.py',))[0], 'fail')

    def test_cited_evidence_paths_are_validated_independently_of_owner(self):
        raw = fixture()
        raw['evidence'][0]['path'] = '../invalid.py'
        full = evaluate(raw)
        self.assertEqual(full['decision']['candidate'], 'src/b.py')
        self.assertEqual(evaluate(raw, 'minus_path_verification')['decision']['candidate'], 'src/a.py')

    def test_memory_retains_actual_prior_evidence_not_only_current_candidate_refs(self):
        raw = fixture()
        raw['evidence'].append({'id': 'earlier_b', 'path': 'src/b.py', 'content': 'prior observation'})
        raw['history'].append({'id': 'earlier_observation', 'candidate': 'src/b.py',
                               'object': 'src/b.py', 'evidence_ref': ['earlier_b']})
        full = evaluate(raw)
        memory = full['module_outputs']['memory']['assessments'][1]
        self.assertIn('earlier_b', memory['evidence_refs'])
        self.assertIn('earlier_observation', memory['event_refs'])
        self.assertNotIn('earlier_b', raw['candidates'][1]['evidence_refs'])
        self.assertEqual(full['decision']['candidate'], 'src/b.py')
        self.assertEqual(evaluate(raw, 'minus_memory')['decision']['candidate'], 'src/a.py')

    def test_memory_states_are_immutable_and_independent_across_tasks_and_trials(self):
        source = Snapshot.from_dict(fixture())
        empty = EvidenceMemory(source.task_id, source.trial_id)
        first = empty.remember(source.history[0], source.evidence)
        second = first.remember(source.history[1], source.evidence)
        self.assertEqual(len(empty.entries), 0)
        self.assertEqual(len(first.entries), 1)
        self.assertEqual(len(second.entries), 2)
        with self.assertRaises(ValueError):
            EvidenceMemory('other_task', source.trial_id).remember(source.history[0], source.evidence)
        with self.assertRaises(ValueError):
            EvidenceMemory(source.task_id, 'other_trial').remember(source.history[0], source.evidence)
        before = evaluate(fixture())['all_module_outputs']['memory']
        other = fixture()
        other['task_id'], other['trial_id'], other['history'] = 'other', 'new', []
        result = evaluate(other)
        self.assertTrue(all(a['verdict'] == 'unknown' for a in result['module_outputs']['memory']['assessments']))
        self.assertEqual(evaluate(fixture())['all_module_outputs']['memory'], before)

    def test_memory_refuses_source_redefinition_and_ignores_unresolved_references(self):
        source = Snapshot.from_dict(fixture())
        memory = EvidenceMemory.from_snapshot(source)
        altered = (replace(source.evidence[0], content='changed'), *source.evidence[1:])
        with self.assertRaises(ValueError):
            memory.remember(source.history[0], altered)
        event = replace(source.history[0], id='missing', evidence_ref=('absent',), verifier=None)
        self.assertEqual(memory.remember(event, source.evidence), memory)

    def test_abstention_removal_returns_candidate_when_evidence_is_insufficient(self):
        raw = {'task_id': 'insufficient', 'repository_files': ['a.py'], 'candidates': [{'path': 'a.py'}]}
        full = evaluate(raw)
        removed = evaluate(raw, 'minus_abstention')
        self.assertEqual(full['decision']['action'], 'abstain')
        self.assertEqual(removed['decision']['candidate'], 'a.py')
        self.assertNotIn('abstention', removed['module_outputs'])
        for module in set(MODULE_NAMES) - {'abstention'}:
            self.assertEqual(full['module_outputs'][module], removed['module_outputs'][module])

    def test_missing_quality_remains_null_despite_available_candidates(self):
        raw = fixture()
        raw['history'] = []
        result = evaluate(raw)
        self.assertEqual(set(result['quality']), {'grounding', 'path', 'verify', 'coherence', 'efficiency'})
        for metric in result['quality'].values():
            self.assertIsNone(metric['value'])
            self.assertFalse(metric['supported'])
            self.assertTrue(metric['missing_reason'])
        self.assertIsNotNone(result['decision']['candidate'])

    def test_quality_uses_canonical_trace_fields_and_reports_resource_denominators(self):
        result = evaluate(fixture())
        quality = result['quality']
        for dimension in ('grounding', 'path', 'verify', 'coherence'):
            self.assertEqual(quality[dimension]['value'], 1.0)
        expected = (4096 / (4096 + 300) + 16 / (16 + 2)) / 2
        self.assertAlmostEqual(quality['efficiency']['value'], expected)
        self.assertEqual(quality['efficiency']['details']['totals']['tokens'], 300)
        self.assertIsNone(quality['efficiency']['details']['totals']['elapsed_ms'])
        self.assertEqual(set(result['trace'][0]), {'id', 'task_id', 'trial_id', 'context', 'action',
                         'object', 'candidate', 'evidence_ref', 'verifier', 'resource'})

    def test_quality_distinguishes_missing_from_observed_failure(self):
        raw = fixture()
        raw['history'][0]['verifier']['status'] = 'fail'
        raw['history'][1]['verifier']['status'] = 'unknown'
        raw['history'][1]['evidence_ref'] = ['missing']
        raw['history'][1]['object'] = '../invalid'
        result = evaluate(raw)['quality']
        self.assertEqual(result['verify']['value'], 0.0)
        self.assertTrue(result['verify']['supported'])
        self.assertEqual(result['coherence']['value'], 1.0)  # verifier refs still introduce b
        self.assertLess(result['path']['value'], 1.0)
        self.assertLess(result['grounding']['value'], 1.0)
        raw['repository_files'] = None
        self.assertIsNone(evaluate(raw)['quality']['path']['value'])

    def test_boundary_rejects_evaluator_fields_at_every_registered_depth(self):
        for key in ('gold_target', 'goldFiles', 'patch', 'posthoc_success', 'FileHit@1', 'first_hit_rank'):
            for location in ('root', 'candidate', 'evidence', 'history', 'verifier', 'resource', 'model_config'):
                with self.subTest(key=key, location=location):
                    raw = fixture()
                    target = {'root': raw, 'candidate': raw['candidates'][0], 'evidence': raw['evidence'][0],
                              'history': raw['history'][0], 'verifier': raw['history'][0]['verifier'],
                              'resource': raw['history'][0]['resource'], 'model_config': raw['model_config']}[location]
                    target[key] = {'nested': 'forbidden'}
                    with self.assertRaises(BoundaryError):
                        evaluate(raw)

    def test_boundary_rejects_unknown_containers_and_json_encoded_leakage(self):
        for value in ({'nested': {'gold_target': 'src/a.py'}}, '{"nested": {"posthoc_success": true}}'):
            raw = fixture()
            raw['context'] = value
            with self.assertRaises(BoundaryError):
                evaluate(raw)
        raw = fixture()
        raw['evidence'][0]['metadata'] = {'benign': 'still unregistered'}
        with self.assertRaises(BoundaryError):
            evaluate(raw)
        raw = fixture()
        raw['model_config']['api_key'] = 'fixture_not_a_secret'
        with self.assertRaises(BoundaryError):
            evaluate(raw)

    def test_snapshot_is_deeply_immutable_and_roundtrips(self):
        raw = fixture()
        before = deepcopy(raw)
        source = Snapshot.from_dict(raw)
        self.assertEqual(Snapshot.from_dict(source.as_dict()), source)
        with self.assertRaises(FrozenInstanceError):
            source.task_id = 'changed'
        with self.assertRaises(FrozenInstanceError):
            source.candidates[0].path = 'changed'
        with self.assertRaises(TypeError):
            source.candidates[0].evidence_refs[0] = 'changed'
        evaluate_conditions(raw)
        self.assertEqual(raw, before)
        raw['evidence'][0]['content'] = 'outside mutation'
        self.assertNotEqual(source.evidence[0].content, raw['evidence'][0]['content'])

    def test_model_reasoning_effort_is_metadata_temperature_is_optional(self):
        result = evaluate(fixture())
        self.assertEqual(result['model_config']['reasoning_effort'], 'max')
        self.assertNotIn('temperature', result['model_config'])
        self.assertEqual(result['implementation_version'], 'audit_framework_v1')
        self.assertEqual(result['parameter_origin'], 'artifact_configuration')

    def test_scope_duplicates_numeric_types_and_condition_names_are_checked(self):
        variants = []
        raw = fixture(); raw['history'][0]['task_id'] = 'different'; variants.append(raw)
        raw = fixture(); raw['history'][0]['trial_id'] = 'different'; variants.append(raw)
        raw = fixture(); raw['candidates'].append(deepcopy(raw['candidates'][0])); variants.append(raw)
        raw = fixture(); raw['evidence'].append(deepcopy(raw['evidence'][0])); variants.append(raw)
        raw = fixture(); raw['history'].append(deepcopy(raw['history'][0])); variants.append(raw)
        raw = fixture(); raw['candidates'][0]['score'] = float('nan'); variants.append(raw)
        raw = fixture(); raw['model_config']['seed'] = True; variants.append(raw)
        for raw in variants:
            with self.subTest(raw=raw):
                with self.assertRaises(BoundaryError):
                    evaluate(raw)
        with self.assertRaises(ValueError):
            evaluate(fixture(), '../unregistered')
        with self.assertRaises(ValueError):
            evaluate_conditions(fixture(), ['full_audit', 'full'])

    def test_output_provenance_and_json_serialization_are_complete(self):
        result = evaluate(fixture())
        json.dumps(result, allow_nan=False)
        for name, module in result['module_outputs'].items():
            self.assertEqual(module['module'], name)
            self.assertEqual(module['provenance']['snapshot_digest'], result['snapshot_digest'])
            self.assertEqual(module['provenance']['implementation'], 'audit_framework_v1')
            self.assertTrue(module['provenance']['source_fields'])
            self.assertEqual(len(module['provenance']['parameters_digest']), 64)
        memory = result['module_outputs']['memory']['assessments'][0]
        self.assertIn('a', memory['evidence_refs'])
        self.assertIn('read_a', memory['tool_refs'])
        self.assertIn('step_a', memory['event_refs'])

    def test_malformed_enum_values_raise_boundary_errors(self):
        for field in ('kind', 'polarity'):
            raw = fixture()
            raw['evidence'][0][field] = ['invalid']
            with self.assertRaises(BoundaryError):
                evaluate(raw)
        raw = fixture()
        raw['history'][0]['verifier']['status'] = {'unregistered': 'pass'}
        with self.assertRaises(BoundaryError):
            evaluate(raw)

    def test_unjustified_candidate_switch_has_zero_observed_coherence(self):
        raw = fixture()
        raw['history'][1]['evidence_ref'] = []
        raw['history'][1]['verifier'] = None
        metric = evaluate(raw)['quality']['coherence']
        self.assertEqual(metric['value'], 0.0)
        self.assertTrue(metric['supported'])
        self.assertIsNone(metric['missing_reason'])

    def test_config_origin_is_provenance_and_parameter_drift_is_rejected(self):
        original_read = Path.read_text
        def origin_read(path, *args, **kwargs):
            row = json.loads(original_read(path, *args, **kwargs))
            row['parameter_origin'] = 'documented_configuration'
            return json.dumps(row)
        with patch.object(Path, 'read_text', origin_read):
            self.assertEqual(load_condition('minus_memory').parameter_origin, 'documented_configuration')
        def drift_read(path, *args, **kwargs):
            row = json.loads(original_read(path, *args, **kwargs))
            if path.name == 'minus_memory.json':
                row['module_parameters']['minimum_grounding_refs'] += 1
            return json.dumps(row)
        with patch.object(Path, 'read_text', drift_read):
            with self.assertRaises(ValueError):
                load_condition('minus_memory')


if __name__ == '__main__':
    unittest.main()
