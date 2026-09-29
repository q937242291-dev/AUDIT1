# Exact-task component diagnostic evidence

`task_join.csv` links the 60 `full_v5` component tasks to seven diagnostic records each in `data/logs/localization_methods/full_audit_localization/audit_verdicts.jsonl`, using exact `instance_id`. `diagnostics_60.jsonl` retains all 420 selected records with original source line numbers.

The join is across runs: the diagnostics were recorded in the 260-task localization run, not in the later component ablation execution. This supports task-matched activation counts, but not same-execution activation attribution.

The source diagnostics yield grounding 1/60, consistency 25/60, path verification 16/60, and memory 14/60 when activation means `warn` or `fail`. These are independently recomputed by `scripts/reproduce_repair_endpoints.py`; no transcribed derived table is used. See `docs/repair_evidence.md` for completion denominators, limitations, and output locations.
