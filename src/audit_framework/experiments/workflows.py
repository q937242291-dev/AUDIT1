"""Require actual recorded reductions and fixed SWE-agent identity."""
import re
from .contracts import MODULES,require

def validate_workflows(config):
 require(isinstance(config,dict) and set(config)=={'fixed','original','reduced'},'Supply --workflow-config with fixed, original and reduced process settings')
 fixed=config['fixed'];keys={'model','reasoning_effort','harness','harness_revision','prompt_sha256','toolset_sha256','evaluation_protocol'}
 require(isinstance(fixed,dict) and set(fixed)==keys and all(isinstance(v,str) and v for v in fixed.values()),'Incomplete fixed workflow identity')
 require(fixed['reasoning_effort']=='max' and fixed['harness']=='SWE-agent' and fixed['harness_revision']!='main','Freeze the actual SWE-agent/max-reasoning protocol')
 for k in ('prompt_sha256','toolset_sha256'):require(re.fullmatch('[0-9a-f]{64}',fixed[k]),f'Invalid {k}')
 for arm in ('original','reduced'):
  row=config[arm];require(isinstance(row,dict) and set(row)=={'context_strategy','memory_budget','enabled_modules'},'Record the actual targeted settings')
  require(isinstance(row['context_strategy'],dict) and row['context_strategy'].get('id'),'Missing context strategy')
  require(type(row['memory_budget']) is int and row['memory_budget']>=0,'Invalid memory budget')
  modules=row['enabled_modules'];require(isinstance(modules,list) and len(modules)==len(set(modules)) and not set(modules)-set(MODULES),'Invalid module configuration')
 original,reduced=config['original'],config['reduced']
 require(set(original['enabled_modules'])==set(MODULES),'Original enables seven modules')
 require(set(reduced['enabled_modules'])<set(original['enabled_modules']),'Record the removed modules')
 require(reduced['memory_budget']<original['memory_budget'] and reduced['context_strategy']!=original['context_strategy'],'Reduced memory/context settings must reflect the recorded intervention')
