# Empirical log collections

Each directory is an empirical-method collection, not a pooled experiment.
log_inventory.csv records the actual file count and size of each collection.
Task/run denominators are separately recomputed in
outputs/analysis/controlled/dataset_denominators.csv after offline analysis.

| Directory | Main use |
|---|---|
| progressive_context | Five source-context conditions; 120 tasks and two seeds |
| tool_search | 280 paired runs over 120 issues |
| identifier_representation | 120 paired runs over 40 issues |
| component_ablation | 60 tasks, nine variants; incomplete records retained |
| component_activity | Exact task join between separate diagnostic and ablation runs |
| localization_methods | Five methods on 260 issues, including verdict/tool records |
| input_projection | Six tasks, three seeds, five input-visibility conditions |
| matched_context | 40 tasks and seven context conditions |
| audit_policy | Six policies, 30 assignments, 14 distinct issues |
| trajectory_replay | 30 tasks, two branches and five checkpoints |
| model_swap | Recovered predictions and path-audit calls for 15 model/slice combinations |
| repair_endpoints | Bounded source tables/test logs and 24 official reports |
| deepswe_success_trajectories | 1,308 success summaries, event indexes, source acquisition and parser provenance |
| swebench_pro_success_trajectories | 584 success summaries and separate acquisition manifest |

Full unreviewed public prompt/response archives are not redistributed. The
acquisition manifests and portable download/parser scripts explain how to obtain
them, while recording missing or inaccessible objects. Compressed repair logs
ending in .gz.b64 are complete sanitized gzip/Base64 logs; the repair script
decodes them. Archival .py.txt snapshots are inspection-only, not live runners.

See docs/data_and_analysis.md for estimators, checks, and acquisition commands.
