# Experiment protocol

Planning validates actual registered identities and produces a deterministic manifest with zero model calls. It does not infer missing tasks from results. Execute only after supplying real outcome-free runtime inputs and a compatible adapter.

```sh
python scripts/run_experiments.py --list
python scripts/run_experiments.py --experiment localization_methods --task-list-root /path/to/task_lists --out runs/method_plan.json
python scripts/run_experiments.py --experiment component_ablation --task-list-root /path/to/task_lists --out runs/component_plan.json
python scripts/run_experiments.py --experiment original_reduced_workflows --task-list-root /path/to/task_lists --workflow-config /path/to/actual_workflow.json --out runs/workflow_plan.json
```

Main method grid:266×5=1,330 jobs. Component grid:60×9=540 jobs. Original/reduced grid:266×2=532 jobs. Limit options select complete task grids, never isolated arms. Registrations are external; the archive has no empirical task lists.

Runtime envelopes have cohort,unit_id,snapshot,repository:{repo,base_commit,state_hash,root}. Optional fields are context_sources,identifier_vocabulary,legal_history_chars. Snapshot task/trial identity must bind to its registration. Gold patches, expected targets and evaluator outcomes never enter runtime/provider snapshots.

All seven component module outputs are computed once from the same snapshot and cached across nine conditions. A removal hides exactly one output; majority retains all outputs and replaces only aggregation. Completed-pair analyses retain planned/completed/error accounting and validate fixed model,prompt,repository,snapshot/output hashes.

Trust-first gates the original solver Top-1 against referenced evidence, actual inspection, ownership/path checks and critical failures. Failure produces abstention while retaining candidates; another candidate cannot silently replace that failed Top-1. Process validity is separate from localization correctness.

The read-only provider adapter supports concrete direct prediction, tool search, candidate fusion and audit postprocessing. Audit policy callbacks run at the actual prefix checkpoint before the next tool action; future candidates/evidence are rejected. no_audit never invokes the audit engine. Shared method generation is cached without mixing measured costs with made-up calls.

For an explicit provider run use `--execute --snapshots ... --adapter audit_framework.experiments.adapters:provider_adapter --provider-config configs/experiments/provider_http.json`. Set AUDIT_BASE_MODEL,AUDIT_HTTP_ENDPOINT,AUDIT_API_KEY externally. The API transmits declared reasoning_effort=max; a rejected effort cannot trigger a silent model/effort fallback or retry. Path-verifier model aliases are AUDIT_PATH_MODEL_SMALL/MEDIUM/NEW. Actual provider identifiers must come from the recorded runs, not paper nicknames guessed by this package.

## Recorded original/reduced workflow settings

`--workflow-config` contains exactly fixed,original,reduced. fixed records model,reasoning_effort="max",harness="SWE-agent",immutable harness_revision,prompt_sha256,toolset_sha256,evaluation_protocol. Each arm records context_strategy:{id:...,...},memory_budget,enabled_modules. Original enables all seven; reduced names its actual removed modules, reduced memory budget and changed context strategy. The workflow configuration records the chosen process settings.

Use an actual SWE-agent adapter exposing paper_protocol equal to fixed and capabilities including repair. The ordinary localization/core adapter cannot execute this grid. Both workflows retain the full execution ledger. Figure6 reports 193 paired successful trajectories.

Pinned source adapters and official grading entry points are documented in third_party_sources.md. Full installed upstream harnesses, Docker/images, task checkouts and model service access are external dependencies. Offline tests validate the runtime and analysis contracts.
