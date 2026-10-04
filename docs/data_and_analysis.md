# External data and offline analysis

All empirical inputs remain external. No task IDs, real outcomes or data tables are bundled. Scripts take `--data-root`; input measurements are never overwritten. Missing observations cannot become zero or successful outcomes.

## Denominators

| Measurement | Unit / required coverage |
|---|---|
| Table 1 / Figure 3 | 1,308 successful public trajectories; four strata ×327; task-cluster bootstrap |
| Table 2 / Table 5 | Same 60 component tasks; nine arms; 540 planned /537 completed rows |
| Table 3 | 240 completed runs per progressive context arm |
| Table 4 | 280 search pairs and120 representation pairs; execution-level inference kept separate from distinct tasks |
| Table 6 | Five methods ×266 distinct Pro Python tasks =1,330 rows |
| Table 7 | Five conditions ×18 distinct tasks =90 rows |
| Table 8 | Seven conditions ×40 distinct tasks =280 rows |
| Table 9 | Six policies ×30 distinct successful tasks |
| Table 10 / Figure 5(b) | Random Verified200 plus full Lite300; Lite slices50/100/150/200/300, same IDs across three models |
| Table 11 / Figure 5(c) | 300 replay rows; 60 rows per checkpoint7/30/90/180/365 |
| Figure 5(d) | 21 bounded tasks and12 official endpoint tasks per branch |
| Figure 6 |193 random paired successful issues within266;20,648 steps;7,348 overlapping redundancy labels |

Table1 means include Other tool step, while named-role signature definitions remain unchanged. Presence flags support backbone cooccurrence, not ordering. Bootstrap defaults are2,000 draws/seed20260922, preserving the source RNG stream.

## Required identities

`benchmark_catalog.json` projects official rows to instance_id,repo,base_commit and records immutable source revision, language filter and catalog checksum. It does not contain patches or outcomes. Pro must use the V1 pin. Verified/Lite require an actual immutable40-character source commit supplied with `--revision`; no current HEAD is guessed.

`prepare_task_registration.py --catalog ... --cohort ... --out ...` creates schema-2 registrations. A subset additionally needs `--task-ids` containing its actual selected IDs. Verified200 needs `--selection` containing a method and actual sampling provenance. For other focused experiments use `--units-json` with the actual identity-only assignment list. Repeated runs cannot replace the paper's distinct-task requirements.

Full reproduction:

```sh
python reproduce.py --data-root /path/to/logs --pro-catalog /path/to/pro_catalog.json --identity-root /path/to/catalogs --task-list-root /path/to/task_lists --out outputs/analysis --figures
```

`identity-root` must contain `verified_catalog.json` and `lite_catalog.json`. Each model/slice has `logs/model_swap/<model_folder>/<verified_200|lite_N>/localization_outputs.jsonl`, plus `run_metadata.json` recording model,changed_component=path_audit_llm_only,catalog_sha256,fixed_protocol. Rows include official instance_id,repo,base_commit,found_files,gold_files,usage.total_tokens. All usage values must be observed. The source model folders are gpt_4_1_mini,gpt_4_1,gpt_5_1.

Component rows retain solver_model, repository_state, base_commit, prompt_template_sha256, snapshot_sha256 and all_module_outputs_sha256. The latter records the identical pre-removal module outputs. Repair evidence_manifest.json additionally records diagnostic_join_mode as same_run or same_task_different_run; actual run IDs must agree with that declaration.

## Figure6 input schema

Three required files under external `logs/redundancy/`:

- `workflow_outcomes.jsonl`: exactly266 distinct official tasks. Each row has instance_id,model_role="GPT-5.6 Luna",original,reduced. Each workflow records status,resolved,evaluator_report_sha256 and fixed model,reasoning_effort,harness,harness_revision,prompt_sha256,toolset_sha256,evaluation_protocol,repo,base_commit,repository_state. Completed outcomes use boolean resolved and an actual report hash. Other statuses retain resolved=null. Both arms must preserve all fixed fields.
- `success_sample.json`: method=random_without_replacement,sampling_frame=luna_original_successes_in_pro_python_266,actual seed,RNG,eligible_task_ids_sha256,selected_task_ids (193). With python.random.Random, the source ordered sample must reproduce from sorted eligible IDs and that seed. Other RNGs require source_selection_sha256. Every selected task must be resolved by both workflows.
- `aligned_steps.jsonl`: instance_id,step_id,categories,omitted,reduced_step_id,alignment. Alignment records actual normalizer_version,method,source_sha256. Omitted=true requires reduced_step_id=null; otherwise it names the matched reduced step. Each of the193 tasks must have actual aligned steps; duplicate step keys fail.

The five category names are Search / Exploration, Edit / Patch, Context / Information acquisition, Validation / Verification, Recovery / History. Category assignments may overlap. Total steps count unique normalized steps; redundancy labels count category assignments on omitted steps. Thus7,348/20,648 is not a count of unique removable steps. Approximate counts in the paper are checked through the displayed absolute and within-category percentages.

The 266-case benchmark source is linked in `../266_CASES_LINKS.md`. Figure 6 manuscript targets and the 193-sample definition are summarized in `../193_SUCCESS_SAMPLE.md`.

## Verification reports

Each stage emits manuscript_comparisons.csv and verification.json. MATCH means all emitted comparisons agree with the manuscript under its display precision. MISMATCH or INPUT_ERROR halts combined analysis. Final analysis_report.json can report complete MATCH only when all five stages have matched; partial runs are PARTIAL_MATCH. Figures3–6 require all stage reports to match.

Public log acquisition remains available with an explicitly supplied external `--manifest` and `--output-root`; no acquisition manifest or downloaded trajectory is bundled. Source verification uses `python scripts/fetch_upstream_sources.py --verify`.
