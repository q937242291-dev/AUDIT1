"""Offline integration tests. No provider, network, container or experiment is run."""
from __future__ import annotations

import ast
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from audit_framework.integrations import (
    PreFinalAuditHook, ToolFeedback, attach_pre_final_audit, assert_installed_swe_agent_pin,
    build_critic_feedback, build_pro_evaluation_invocation, build_swe_agent_invocation,
    gather_pro_predictions, merge_mini_metadata, parse_trajectory,
    select_task_memory, snapshot_from_trajectory, source_info, source_manifest,
)
from audit_framework.integrations.__main__ import main
from audit_framework.integrations.upstream import verified_path, load_pure_module


def sample_snapshot():
    return {'task_id': 'repo__issue-17', 'trial_id': 'trial-2',
            'candidates': [{'path': 'src/cache.py', 'evidence_refs': ['read:1']}],
            'evidence': [{'id': 'read:1', 'kind': 'source', 'path': 'src/cache.py',
                          'content': 'def invalidate(key): ...', 'owner': 'src/cache.py'}],
            'repository_files': ['src/cache.py']}


class OfflineTest(unittest.TestCase):
    def setUp(self):
        self.guard = patch.object(socket.socket, 'connect', side_effect=AssertionError('Network prohibited in integration tests'))
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.temp = tempfile.TemporaryDirectory(prefix='audit-integration-')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)

    def test_all_source_hashes_and_licenses(self):
        manifest = source_manifest()
        self.assertEqual(len(manifest['sources']), 4)
        for name, info in manifest['sources'].items():
            self.assertRegex(info['commit'], r'^[0-9a-f]{40}$')
            self.assertEqual(info['license'], 'MIT')
            license_text = verified_path(name, info['license_file']).read_text(encoding='utf-8')
            self.assertIn('Copyright', license_text)
            self.assertIn('Permission is hereby granted', license_text)
            for file, expected in info['files'].items():
                actual = verified_path(name, file).read_bytes()
                self.assertEqual(hashlib.sha256(actual).hexdigest(), expected['sha256'])

    def test_original_mini_merge_is_called(self):
        original = load_pure_module('mini_swe_agent', 'src/minisweagent/utils/serialize.py')
        self.assertIn('third_party', original.__file__)
        a = {'config': {'agent': {'a': 1}}, 'messages': [{'role': 'user', 'content': 'issue'}]}
        b = {'config': {'agent': {'b': 2}}}
        before = deepcopy(a)
        self.assertEqual(merge_mini_metadata(a, b)['config']['agent'], {'a': 1, 'b': 2})
        self.assertEqual(a, before)
        self.assertEqual(original.recursive_merge({'x': original.UNSET, 'y': 3}), {'y': 3})

    def test_swe_trace_keeps_ids_and_excludes_evaluator_metadata(self):
        raw = {'info': {'resolved': True, 'submission': 'HIDDEN'},
               'trajectory': [{'action': 'cat src/cache.py', 'observation': 'source', 'thought': 'inspect'},
                              {'action': 'submit', 'observation': 'HIDDEN_FINAL'}]}
        before = deepcopy(raw)
        trace = parse_trajectory(raw, source='swe_agent', task_id='repo__issue-17', trial_id='trial-2')
        snapshot = snapshot_from_trajectory(trace, before_index=1, candidates=[], repository_files=[])
        self.assertEqual(snapshot['task_id'], 'repo__issue-17')
        self.assertEqual(snapshot['history'][0]['trial_id'], 'trial-2')
        self.assertNotIn('HIDDEN', json.dumps(snapshot))
        self.assertEqual(raw, before)
        self.assertIsNone(snapshot['evidence'][0]['verified'])

    def test_mini_formats(self):
        fence = chr(96) * 3
        raw = {'messages': [{'role': 'system', 'content': 'system'}, {'role': 'user', 'content': 'issue'},
                           {'role': 'assistant', 'content': fence + 'bash\nls src\n' + fence},
                           {'role': 'user', 'content': 'cache.py'}]}
        old = parse_trajectory(raw, source='mini_swe_agent', task_id='mini-17')
        self.assertEqual(old.events[2].action.strip(), 'ls src')
        raw['trajectory_format'] = 'mini-swe-agent-1.1'
        raw['messages'][2]['extra'] = {'actions': [{'command': 'ls src'}]}
        new = parse_trajectory(raw, source='mini_swe_agent', task_id='mini-17')
        self.assertEqual(json.loads(new.events[2].action), [{'command': 'ls src'}])
        self.assertEqual(new.events[3].observation, 'cache.py')

    def test_deepswe_structured_tool_results(self):
        raw = {'steps': [{'source': 'agent', 'message': 'inspect',
                          'tool_calls': [{'tool_call_id': 't1', 'function_name': 'bash', 'arguments': {'command': 'ls'}}],
                          'observation': {'results': [{'source_call_id': 't1', 'content': 'src'}]}}],
               'final_metrics': {'reward': 1}}
        trace = parse_trajectory(raw, source='deepswe', task_id='task/unchanged-id')
        self.assertEqual(trace.events[0].raw_index, 0)
        self.assertEqual(json.loads(trace.events[0].observation)['results'][0]['source_call_id'], 't1')
        self.assertNotIn('reward', json.dumps(trace.as_dict()))

    def test_parser_rejects_malformed_or_unknown_formats(self):
        for raw, source in [({'trajectory': [None]}, 'swe_agent'), ({'steps': 'x'}, 'deepswe'),
                            ({'messages': [], 'trajectory_format': 'future'}, 'mini_swe_agent')]:
            with self.assertRaises(ValueError):
                parse_trajectory(raw, source=source, task_id='x')

    def test_terminal_messages_and_invalid_cutoffs_rejected(self):
        trace = parse_trajectory({'messages': [{'role': 'exit', 'content': 'done'}]}, source='mini_swe_agent', task_id='x')
        for cutoff in (-1, True, 2, 1):
            with self.assertRaises(ValueError):
                snapshot_from_trajectory(trace, before_index=cutoff, candidates=[])

    def test_hook_dispatches_before_action_and_calls_real_engine(self):
        # Execute the original hook dispatcher classes without importing the external
        # model/environment stack. Only their type annotations are supplied locally.
        source = verified_path('swe_agent', 'sweagent/agent/hooks/abstract.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        body = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        scope = {'StepOutput': SimpleNamespace, 'AgentInfo': dict, 'Trajectory': list}
        exec(compile(ast.Module(body=body, type_ignores=[]), '<pinned-upstream-hook-dispatch>', 'exec'), scope)
        timeline = []
        step = SimpleNamespace(action='finalize_localization', extra_info={})
        snapshot = sample_snapshot()
        def factory(agent, outgoing):
            timeline.append('snapshot')
            self.assertEqual(outgoing.action, 'finalize_localization')
            return snapshot
        def apply(outgoing, result):
            timeline.append('decision')
            outgoing.extra_info['audit'] = result['decision']
            outgoing.action = json.dumps(result['decision'])
        hook = PreFinalAuditHook(factory, is_final_action=lambda s: s.action == 'finalize_localization', apply_decision=apply)
        dispatcher = scope['CombinedAgentHook']([hook])
        dispatcher.on_init(agent=SimpleNamespace())
        dispatcher.on_run_start()
        dispatcher.on_actions_generated(step=step)
        timeline.append('dispatch-action')
        self.assertEqual(timeline, ['snapshot', 'decision', 'dispatch-action'])
        self.assertEqual(len(hook.records[0]['results']), 9)
        self.assertEqual(hook.records[0]['phase'], 'before_final_localization')
        self.assertEqual(snapshot, sample_snapshot())
        self.assertEqual(step.extra_info['audit']['candidate'], 'src/cache.py')

    def test_hook_ignores_nonfinal_steps(self):
        called = []
        hook = PreFinalAuditHook(lambda a, s: called.append(s), is_final_action=lambda s: False,
                                apply_decision=lambda s, r: called.append(r))
        hook.on_actions_generated(step=SimpleNamespace(action='ls'))
        self.assertEqual(called, [])

    def test_hook_rejects_outcomes_before_apply(self):
        called = []
        hook = PreFinalAuditHook(lambda a, s: {**sample_snapshot(), 'resolved': True},
                                is_final_action=lambda s: True, apply_decision=lambda s, r: called.append(r))
        hook.on_init(agent=object())
        with self.assertRaises(ValueError):
            hook.on_actions_generated(step=SimpleNamespace(action='final'))
        self.assertEqual(called, [])

    def test_pin_attestation_and_attach(self):
        info = source_info('swe_agent')
        direct = {'url': 'https://github.com/' + info['repository'] + '.git',
                  'vcs_info': {'commit_id': info['commit']}}
        dist = SimpleNamespace(read_text=lambda _: json.dumps(direct))
        class Agent:
            def add_hook(self, hook):
                self.hook = hook
                hook.on_init(agent=self)
        with patch('audit_framework.integrations.swe_agent.metadata.distribution', return_value=dist):
            assert_installed_swe_agent_pin()
            agent = Agent()
            hook = attach_pre_final_audit(agent, lambda a, s: sample_snapshot(),
                                         is_final_action=lambda s: True, apply_decision=lambda s, r: None)
            self.assertIs(agent.hook, hook)
            direct['vcs_info']['commit_id'] = '0' * 40
            with self.assertRaises(RuntimeError):
                assert_installed_swe_agent_pin()

    def test_pinned_invocation_records_fixed_inputs_without_running(self):
        repo = self.work / 'repo'; repo.mkdir()
        config = self.work / 'config.yaml'; config.write_text('agent: {}', encoding='utf-8')
        issue = self.work / 'issue.md'; issue.write_text('Fix cache invalidation', encoding='utf-8')
        args = dict(config=config, repository=repo, issue_file=issue, output_dir=self.work / 'out',
                    model='fixture-model', cost_limit=1.0)
        plan = build_swe_agent_invocation(**args)
        self.assertIn(source_info('swe_agent')['commit'], plan.install_requirement)
        self.assertIn('--actions.open_pr=false', plan.argv)
        self.assertEqual(plan.prompt_sha256, hashlib.sha256(issue.read_bytes()).hexdigest())
        self.assertFalse((self.work / 'out').exists())
        for override in ({'commit': '0' * 40}, {'cost_limit': float('nan')}, {'output_dir': repo / 'out'}):
            with self.assertRaises(ValueError):
                build_swe_agent_invocation(**{**args, **override})

    def test_original_pro_gatherer_and_pred_ambiguity(self):
        folder = self.work / 'instance_fixture'; folder.mkdir()
        pred = folder / 'instance_fixture.pred'
        pred.write_text(json.dumps({'instance_id': 'id-preserved', 'model_patch': 'diff --git a/a b/a\n'}), encoding='utf-8')
        rows = gather_pro_predictions(self.work, model_name='fixture-model')
        self.assertEqual(rows, [{'instance_id': 'id-preserved', 'patch': 'diff --git a/a b/a\n', 'prefix': 'fixture-model'}])
        (folder / 'duplicate.pred').write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):
            gather_pro_predictions(self.work, model_name='fixture-model')

    def test_official_pro_command_uses_local_offline_grading_flags(self):
        samples = self.work / 'samples.csv'; samples.write_text('instance_id\nfixture\n', encoding='utf-8')
        preds = self.work / 'preds.json'; preds.write_text('[]', encoding='utf-8')
        plan = build_pro_evaluation_invocation(raw_sample_path=samples, patch_path=preds,
                    scripts_dir=self.work, output_dir=self.work / 'out', dockerhub_username='public-fixture')
        self.assertIn('--use_local_docker', plan['argv'])
        self.assertIn('--block_network', plan['argv'])
        self.assertFalse(plan['executed'])
        self.assertFalse((self.work / 'out').exists())

    def test_original_gatherer_preserves_utf8_and_dataset_ids(self):
        folder = self.work / 'instance_unicode'; folder.mkdir()
        body = {'instance_id': 'repo__unicode-17', 'model_patch': '+缓存 = "✅"\n'}
        (folder / 'sample.pred').write_text(json.dumps(body, ensure_ascii=False), encoding='utf-8')
        rows = gather_pro_predictions(self.work, model_name='fixture')
        self.assertEqual(rows[0]['instance_id'], body['instance_id'])
        self.assertEqual(rows[0]['patch'], body['model_patch'])

    def test_modified_source_hash_is_rejected(self):
        from audit_framework.integrations import upstream
        spec = deepcopy(source_info('mini_swe_agent'))
        spec['files']['src/minisweagent/utils/serialize.py']['sha256'] = '0' * 64
        with patch.object(upstream, 'source_info', return_value=spec):
            with self.assertRaises(ValueError):
                merge_mini_metadata({'a': 1})

    def test_critic_uses_observed_feedback_without_fabricated_verification(self):
        item = ToolFeedback('t', 'r', 'e1', 'tool:1', 'python -m pytest test_cache.py', 'assertion failed', 1)
        result = build_critic_feedback('Find cache bug', 'src/cache.py', item)
        self.assertIn('Execution: python -m pytest', result['prompt'])
        self.assertIn('\nOutput: assertion failed\n', result['prompt'])
        self.assertEqual(result['verifier']['status'], 'fail')
        self.assertIsNone(result['evidence']['verified'])
        self.assertEqual(result['source']['reuse'], 'adapted_prompt_layout')

    def test_memory_scoped_to_prior_same_trial(self):
        def episode(task, trial, i):
            return dict(task_id=task, trial_id=trial, event_index=i, summary='Observed source', evidence_refs=['e1'])
        rows = [episode('t','r',0), episode('t','r',2), episode('t','r',3), episode('t','other',1), episode('other','r',1)]
        self.assertEqual([r['event_index'] for r in select_task_memory(rows, task_id='t', trial_id='r', before_index=3)], [0,2])
        self.assertEqual(select_task_memory(rows, task_id='t', trial_id='r', before_index=3, limit=0), [])
        with self.assertRaises(ValueError):
            select_task_memory([{**rows[0], 'resolved': True}], task_id='t', trial_id='r', before_index=3)

    def test_cli_audit_prefix_calls_all_conditions(self):
        trace = self.work / 'trace.json'
        trace.write_text(json.dumps({'trajectory': [{'action': 'ls', 'observation': 'src'}]}), encoding='utf-8')
        context = self.work / 'context.json'; context.write_text('{"candidates": []}', encoding='utf-8')
        output = io.StringIO()
        with redirect_stdout(output):
            main(['audit-prefix', '--trajectory', str(trace), '--source', 'swe_agent', '--task-id', 't',
                  '--before-index', '1', '--context', str(context)])
        result = json.loads(output.getvalue())
        self.assertEqual(len(result), 9)
        self.assertEqual(len({r['snapshot_digest'] for r in result.values()}), 1)


if __name__ == '__main__':
    unittest.main()
