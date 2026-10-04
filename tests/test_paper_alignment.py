"""Offline invariants using explicitly synthetic identities, never paper outcomes."""
from __future__ import annotations
from copy import deepcopy
import importlib.util,json,random,sys,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from audit_framework.experiments.benchmarks import BENCHMARKS,identity_catalog,validate_catalog
from audit_framework.experiments.cohorts import cohort_from_catalog,seal_registration,verify_registration
from audit_framework.experiments.contracts import MODULES,ProtocolError,digest
from audit_framework.experiments.planning import build_plan
from audit_framework.experiments.workflows import validate_workflows
ROOT=Path(__file__).resolve().parents[1]
def script(name):
 spec=importlib.util.spec_from_file_location('alignment_'+name,ROOT/'scripts'/('reproduce_'+name+'.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
controlled=script('controlled_experiments');redundancy=script('redundancy')
# Existing parser/bootstrap tests participate in the standard offline suite.
ObservedTrajectoryTests=script('success_trajectories').ReproductionTests
RepairEvidenceTests=script('repair_endpoints').EvidenceTests

def fixture_catalog():
 return identity_catalog([dict(instance_id=f'synthetic_only_{i:03}',repo='fixture/repo',base_commit='1'*40,repo_language='python') for i in range(266)],'pro_python_266')
def fixture_workflows():
 return dict(fixed=dict(model='fixture-model',reasoning_effort='max',harness='SWE-agent',harness_revision='1'*40,prompt_sha256='2'*64,toolset_sha256='3'*64,evaluation_protocol='fixture-evaluator'),original=dict(context_strategy={'id':'original_fixture'},memory_budget=100,enabled_modules=list(MODULES)),reduced=dict(context_strategy={'id':'reduced_fixture'},memory_budget=50,enabled_modules=list(MODULES[:-1])))
def fixture_outcomes(catalog):
 rows=[]
 for task in catalog['tasks']:
  run=dict(status='completed',resolved=True,model='fixture-model',reasoning_effort='max',harness='SWE-agent',harness_revision='1'*40,prompt_sha256='2'*64,toolset_sha256='3'*64,evaluation_protocol='fixture-evaluator',repo=task['repo'],base_commit=task['base_commit'],repository_state='4'*40,evaluator_report_sha256='5'*64)
  rows.append(dict(instance_id=task['instance_id'],model_role='GPT-5.6 Luna',original=deepcopy(run),reduced=deepcopy(run)))
 return rows
def fixture_selection(by_id):
 eligible=sorted(by_id)
 return dict(method='random_without_replacement',sampling_frame='luna_original_successes_in_pro_python_266',seed=7,rng='python.random.Random',eligible_task_ids_sha256=digest(eligible),selected_task_ids=random.Random(7).sample(eligible,193))

class PaperAlignmentTests(unittest.TestCase):
 def setUp(self):self.catalog=fixture_catalog()
 def test_frozen_catalog_projects_266_identities(self):
  self.assertEqual(self.catalog['task_count'],266);self.assertEqual(set(self.catalog['tasks'][0]),{'instance_id','repo','base_commit'})
 def test_non_python_rows_are_excluded(self):
  rows=[dict(r,repo_language='python') for r in self.catalog['tasks']]+[dict(instance_id='js_fixture',repo='fixture/js',base_commit='1'*40,repo_language='js')]
  self.assertEqual(identity_catalog(rows,'pro_python_266'),self.catalog)
 def test_duplicate_catalog_identity_is_rejected(self):
  rows=[dict(r,repo_language='python') for r in self.catalog['tasks']];rows[-1]=rows[0]
  with self.assertRaises(ProtocolError):identity_catalog(rows,'pro_python_266')
 def test_latest_revision_cannot_replace_frozen_release(self):
  with self.assertRaises(ProtocolError):identity_catalog([],'pro_python_266',revision='main')
  with self.assertRaises(ProtocolError):identity_catalog([],'pro_python_266',revision='f'*40)
 def test_catalog_tamper_is_rejected(self):
  catalog=deepcopy(self.catalog);catalog['tasks'][0]['repo']='changed'
  with self.assertRaises(ProtocolError):validate_catalog(catalog)
 def test_pro_registration_requires_official_catalog(self):
  with self.assertRaises(ProtocolError):seal_registration('localization_methods',self.catalog['tasks'],source='fixture')
 def test_repeated_execution_cannot_replace_distinct_projection_tasks(self):
  units=[dict(instance_id=f'fixture_{i//3}',replicate=str(i%3)) for i in range(18)]
  with self.assertRaises(ProtocolError):seal_registration('input_projection',units,source='fixture')
 def test_repository_identity_binding_is_checked(self):
  registration=cohort_from_catalog('localization_methods',self.catalog);registration['units'][0]['base_commit']='changed';registration['registration_sha256']=digest({k:v for k,v in registration.items() if k!='registration_sha256'})
  with self.assertRaises(ProtocolError):verify_registration(registration)
 def test_original_and_reduced_plan_has_532_jobs_without_calls(self):
  with TemporaryDirectory() as d:
   path=Path(d);(path/'original_reduced_workflows.json').write_text(json.dumps(cohort_from_catalog('original_reduced_workflows',self.catalog)))
   plan=build_plan('original_reduced_workflows',task_list_root=path,workflow_config=fixture_workflows())
  self.assertEqual((plan['planned_jobs'],plan['provider_calls']),(532,0));self.assertEqual(len({j['instance_id'] for j in plan['jobs']}),266)
 def test_unknown_workflow_settings_are_not_invented(self):
  with self.assertRaises(ProtocolError):validate_workflows(None)
 def test_workflow_requires_fixed_max_reasoning(self):
  config=fixture_workflows();config['fixed']['reasoning_effort']='low'
  with self.assertRaises(ProtocolError):validate_workflows(config)
 def test_workflow_requires_actual_reduction(self):
  config=fixture_workflows();config['reduced']=deepcopy(config['original'])
  with self.assertRaises(ProtocolError):validate_workflows(config)
 def test_main_localization_plan_has_1330_jobs(self):
  with TemporaryDirectory() as d:
   path=Path(d);(path/'localization_methods.json').write_text(json.dumps(cohort_from_catalog('localization_methods',self.catalog)))
   plan=build_plan('localization_methods',task_list_root=path)
  self.assertEqual((plan['planned_jobs'],plan['summary']['localization_methods']['unique_task_ids']),(1330,266))
 def test_old_260_grid_cannot_be_relabelled_266(self):
  rows=[dict(instance_id=r['instance_id'],method_id=aliases[0]) for aliases,_ in controlled.METHOD_ALIASES for r in self.catalog['tasks'][:260]]
  with self.assertRaises(ValueError):controlled.validate_method_grid(rows,self.catalog)
 def test_missing_method_task_is_not_dropped_by_intersection(self):
  rows=[dict(instance_id=r['instance_id'],method_id=aliases[0]) for aliases,_ in controlled.METHOD_ALIASES for r in self.catalog['tasks']]
  rows.pop()
  with self.assertRaises(ValueError):controlled.validate_method_grid(rows,self.catalog)
 def test_six_issues_times_three_seeds_is_not_eighteen_tasks(self):
  with self.assertRaises(ValueError):controlled.validate_distinct_grid([dict(task_id=f'fixture_{i//3}',condition='c') for i in range(18)],'condition','task_id',18)
 def test_random_193_sample_is_reproduced_from_recorded_seed(self):
  by_id=redundancy.validate_outcomes(fixture_outcomes(self.catalog),self.catalog);selection=fixture_selection(by_id)
  self.assertEqual(len(redundancy.validate_selection(selection,by_id)),193)
 def test_changed_random_seed_is_rejected(self):
  by_id=redundancy.validate_outcomes(fixture_outcomes(self.catalog),self.catalog);selection=fixture_selection(by_id);selection['seed']=8
  with self.assertRaises(ProtocolError):redundancy.validate_selection(selection,by_id)
 def test_reduced_failure_cannot_enter_paired_success_sample(self):
  by_id=redundancy.validate_outcomes(fixture_outcomes(self.catalog),self.catalog);selection=fixture_selection(by_id);by_id[selection['selected_task_ids'][0]]['reduced']['resolved']=False
  with self.assertRaises(ProtocolError):redundancy.validate_selection(selection,by_id)
 def test_265_task_ledger_is_not_complete(self):
  with self.assertRaises(ProtocolError):redundancy.validate_outcomes(fixture_outcomes(self.catalog)[:-1],self.catalog)
 def test_category_overlap_preserves_event_and_step_denominators(self):
  row=dict(instance_id='fixture',step_id='s',categories=list(redundancy.CATEGORIES),omitted=True,reduced_step_id=None,alignment=dict(normalizer_version='fixture',method='fixture',source_sha256='1'*64))
  table,summary=redundancy.aggregate_steps([row],{'fixture'})
  self.assertEqual((summary['total_steps'],summary['redundancy_labels'],summary['unique_omitted_steps']),(1,5,1));self.assertEqual(len(table),5)
 def test_duplicate_aligned_step_is_rejected(self):
  row=dict(instance_id='fixture',step_id='s',categories=list(redundancy.CATEGORIES),omitted=True,reduced_step_id=None,alignment=dict(normalizer_version='fixture',method='fixture',source_sha256='1'*64))
  with self.assertRaises(ProtocolError):redundancy.aggregate_steps([row,row],{'fixture'})
 def test_manuscript_mismatch_is_not_reported_as_success(self):
  with TemporaryDirectory() as d:
   result=controlled.write_verification(Path(d),[dict(item='fixture',metric='n',actual=260,manuscript=266,status='MISMATCH')],[])
   self.assertEqual(result['status'],'MISMATCH');self.assertEqual(len(result['mismatches']),1)
if __name__=='__main__':unittest.main()
