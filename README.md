# AUDIT Framework — 1.1.3

Agent Utility and Dependency Intervention Testing. This complete source distribution aligns the analysis contracts and output numbering with the supplied current manuscript. Main controlled cohort: **266 distinct SWE-bench Pro V1 Python tasks**. Figure 6: **193 Luna paired successful trajectories**. Task data and empirical logs are external.

## Quick start

Python 3.10 or newer, from the project root:

```sh
python -m pip install --no-deps -e .
python reproduce.py --tests-only
python scripts/verify_artifact.py
python scripts/fetch_upstream_sources.py --verify
python scripts/prepare_task_registration.py --links
python scripts/run_experiments.py --list
```

Tests and link listing work without datasets, model providers or Docker. Unit fixtures are explicitly synthetic and do not represent experimental observations. Figure rendering additionally requires `pip install -r requirements.txt`. Explicit official identity fetching optionally requires `pip install datasets`.

## Contents

| Path | Purpose |
|---|---|
| src/audit_framework/ | Audit modules, controllers, boundaries, runtime and integrations |
| configs/conditions/ | Full audit, seven single removals and majority controller |
| configs/experiments/ | Registered experiment arms, model aliases and HTTP configuration |
| scripts/ | Identity registration, all paper analysis stages, figures and source verification |
| tests/ | 132 offline unit and contract tests |
| third_party/ | All 21 pinned source files, four source licenses and acquisition locks |
| docs/paper_map.csv | Current Tables 1–11 and Figures 3–6 to script/output mapping |
| docs/data_and_analysis.md | External input contracts and reproduction instructions |
| docs/experiment_protocol.md | Planning, execution and original/reduced workflow contracts |
| CHANGELOG.md | Human-readable modification log |
| MODIFICATION_LOG.json | File-level changes with old and new SHA-256 hashes |
| artifact_manifest.json / sha256sums.txt | Integrity checks for every delivered file |

## External benchmark identities

The official source is [ScaleAI/SWE-bench_Pro](https://huggingface.co/datasets/ScaleAI/SWE-bench_Pro). For the paper's 266-task denominator, use the frozen V1 configuration and filter `repo_language=python`; the current default dataset is not a substitute for that release. The immutable source and supplementary Verified/Lite links are in `docs/data_links.md`.

Create identity-only registrations from your actual official rows/catalog. Nothing is downloaded without `--fetch`:

```sh
python scripts/prepare_task_registration.py --benchmark pro_python_266 --cohort localization_methods --rows-jsonl /path/to/official_v1_rows.jsonl --out /path/to/task_lists
python scripts/run_experiments.py --experiment localization_methods --task-list-root /path/to/task_lists --out runs/localization_plan.json
```

The localization grid has 1,330 planned jobs (266 × five methods). The original/reduced grid has 532 jobs (266 × two workflows). Planning makes zero provider calls. Runs require actual runtime inputs and an explicitly activated adapter. Original/reduced execution additionally requires recorded workflow settings and a bound SWE-agent adapter; generic localization adapters cannot silently stand in for it.

## Reproduce paper measurements

```sh
python reproduce.py --data-root /path/to/actual_logs --pro-catalog /path/to/pro_catalog.json --identity-root /path/to/benchmark_catalogs --task-list-root /path/to/task_lists --out outputs/analysis
```

Add `--figures` after installing figure dependencies. To validate one stage, pass e.g. `--stages observational`. Each stage writes measured results, manuscript comparisons and a verification report. Any missing identity, altered denominator or mismatched value produces a failure; a partial run is reported as `PARTIAL_MATCH`. Numerical targets are comparison values only.

## Audit evidence directly

```sh
audit-framework conditions
audit-framework validate --snapshot examples/trace_snapshot.json
audit-framework ablate --snapshot examples/trace_snapshot.json --out outputs/example_grid.json
```

The component engine evaluates all seven module outputs once, removes one output per ablation and changes only aggregation for the majority arm. Trust-first checks the solver's original Top-1; a failed gate abstains while retaining candidates for inspection. Gold labels, final patches and evaluator outcomes remain outside model-facing snapshots.

132 code tests and 144 Table 1 comparisons passed in this build. Benchmark access and the paper's success-sample statistics are documented in `266_CASES_LINKS.md` and `193_SUCCESS_SAMPLE.md`.
