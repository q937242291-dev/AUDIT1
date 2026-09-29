# Evidence, logs, and analysis

The delivered measurements are inputs. Numerical reproduction reads them and
writes a separate output directory. It never invokes a language model, applies
a patch, or starts a benchmark environment. Code contract tests use small
fixtures and are not additional experimental observations.

## Layout and denominators

| Collection under data/logs | Unit of analysis | Analysis entry point |
|---|---|---|
| progressive_context | Task × seed × five context conditions | reproduce_controlled_experiments.py |
| tool_search | Completed same-task/replicate one-shot–search pairs | reproduce_controlled_experiments.py |
| identifier_representation | Same-task/replicate natural–mutated pairs | reproduce_controlled_experiments.py |
| component_ablation | 60 task IDs × nine configurations; completion recorded separately | reproduce_controlled_experiments.py |
| component_activity | Task-key diagnostic activation joined to component outcomes | reproduce_repair_endpoints.py |
| localization_methods | 260 task IDs × five methods | reproduce_controlled_experiments.py |
| input_projection | Task × seed × five visibility conditions | reproduce_controlled_experiments.py |
| matched_context | 40 tasks × seven context arms | reproduce_controlled_experiments.py |
| audit_policy | Policy-assignment/task key × six policies | reproduce_controlled_experiments.py |
| trajectory_replay | Task × branch × five checkpoint conditions | reproduce_controlled_experiments.py |
| model_swap | Model × recorded common-task slice | reproduce_model_swap.py |
| repair_endpoints | Bounded test conditions and separate official evaluation reports | reproduce_repair_endpoints.py |
| deepswe_success_trajectories | 1,308 successful run-level trajectories, four strata | reproduce_success_trajectories.py |
| swebench_pro_success_trajectories | 584 successful run-level trajectories, separate provenance | parse_public_trajectory_logs.py |

All entry points are under scripts/. data/controlled contains scored records
and summaries; data/logs contains evidence grouped by empirical method.
Data identifiers are join keys and are not silently renamed into new methods.
Do not pool source slices or substitute planned runs for completed pairs.
Missing outcomes remain missing, not failures or zero-cost runs.

## Reproduce tables and figures without model calls

~~~sh
python reproduce.py --out outputs/analysis
python -m pip install -r requirements.txt
python reproduce.py --out outputs/analysis --figures
~~~

The first command needs only the Python standard library. The second installs
optional plotting and PDF dependencies. Outputs contain the table CSVs,
underlying estimates, explicit denominators, and optional figure files.
The delivered results/ directory is not overwritten.

Equation 2 uses mean(Y_full − Y_removed) on completed matched pairs.
Exact McNemar tests use discordant pairs; gains/losses have an explicitly
stated comparison direction. Wilson intervals are descriptive binomial
intervals, not paired-effect intervals or evidence of equivalence.

DeepSWE bootstrap uses task-name clusters, 2,000 draws, and seed 20260922.
The task-any estimator asks whether any successful run of a task contains a
unit. The trajectory-preserving estimator resamples complete task clusters and
takes the ratio of positive runs to all runs. These are different estimands
and retain different column names. Quantiles use the specified ordered-draw
indices rather than interpolating. Stratum interval envelopes are not a
pooled confidence interval. No repository grouping is inferred when absent.
Behavior signatures are sets of observed normalized units, not causal order.
The other_tool_step-inclusive unit count is a separate field.

## Obtain full public trajectories

The shipped success summaries and event indexes have source acquisition
manifests with per-object URLs, task/run IDs, and available checksums. Full
public prompt/response bodies are acquired separately; this avoids pretending
that an unavailable object is a recovered trajectory.

~~~sh
python scripts/fetch_public_trajectory_logs.py
python scripts/fetch_public_trajectory_logs.py --dataset swebench-pro
python scripts/fetch_public_trajectory_logs.py --probe --limit 2 --output-root outputs/probe
python scripts/fetch_public_trajectory_logs.py --download --output-root acquired_logs
python scripts/fetch_public_trajectory_logs.py --dataset swebench-pro --download --output-root acquired_logs
python scripts/parse_public_trajectory_logs.py --help
~~~

The first two commands show acquisition plans without network requests.
Only explicit probe/download flags contact the URLs in the manifests. Failed
downloads stay in the acquisition report. Parsers validate hashes when supplied
and retain completion accounting. Inspect current source access terms before
redistributing downloaded bodies; no private credential is supplied by this
package. Parser snapshots and original-source hashes are in each provenance
directory. Logs ending in .gz.b64 are gzip/Base64 encoded; the repair analysis
decodes and checks them without executing their contents.

## Data integrity

~~~sh
python scripts/verify_artifact.py
~~~

The manifest hashes the release copies of code, configuration, evidence, and
results. Hash checks establish file integrity, not official benchmark success.
Source/evaluation provenance is retained separately inside the evidence files.

