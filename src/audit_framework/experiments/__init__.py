"""Planning and opt-in execution for the paper's registered experiment families."""
from .contracts import ProtocolError, align_completed_pairs
from .planning import build_plan
from .runner import execute_plan, load_runtime_inputs

__all__ = ['ProtocolError', 'align_completed_pairs', 'build_plan', 'execute_plan', 'load_runtime_inputs']
