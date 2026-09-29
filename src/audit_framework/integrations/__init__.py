"""Offline source adapters and explicit pinned harness integration contracts."""
from .feedback import ToolFeedback, build_critic_feedback, select_task_memory
from .repair import build_pro_evaluation_invocation, gather_pro_predictions
from .swe_agent import (PinnedInvocation, PreFinalAuditHook, assert_installed_swe_agent_pin,
                        attach_pre_final_audit, build_swe_agent_invocation, validate_swe_agent_config)
from .trajectories import CanonicalEvent, CanonicalTrajectory, parse_trajectory, snapshot_from_trajectory
from .upstream import merge_mini_metadata, source_info, source_manifest

__all__ = ['ToolFeedback', 'build_critic_feedback', 'select_task_memory',
           'build_pro_evaluation_invocation', 'gather_pro_predictions',
           'PinnedInvocation', 'PreFinalAuditHook', 'assert_installed_swe_agent_pin',
           'attach_pre_final_audit', 'build_swe_agent_invocation', 'validate_swe_agent_config',
           'CanonicalEvent', 'CanonicalTrajectory', 'parse_trajectory', 'snapshot_from_trajectory',
           'merge_mini_metadata', 'source_info', 'source_manifest']
