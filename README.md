# AUDIT Framework



**Agent Utility and Dependency Intervention Testing**

AUDIT keeps process observations, matched localization necessity, repair
outcomes, completion, and resource cost separate. It provides independently
registered audit modules, explicit controller replacement, trace schemas,
information-boundary checks, experiment configurations, and offline analysis.

## Quick start

Python 3.10 or newer. Run these commands from this directory:

~~~sh
python -m pip install --no-deps -e .
python reproduce.py --tests-only
python scripts/verify_artifact.py
audit-framework conditions
audit-framework ablate --snapshot examples/trace_snapshot.json --out outputs/example_grid.json
~~~

These commands do not call model providers or rerun experiments. Unit and
contract tests use fixtures, not additional empirical observations.
The delivered data/ and results/ are inputs/read-only release artifacts;
commands write new outputs separately under outputs/.

## Code and directories

| Path | Purpose |
|---|---|
| src/audit_framework/ | AUDIT implementation and command-line entry point |
| src/audit_framework/integrations/ | Upstream source and harness adapters |
| src/audit_framework/experiments/ | Experimental conditions, inputs, schedules, and execution contracts |
| configs/conditions/ | Full audit, seven single removals, and majority controller |
| configs/experiments/ | Experiment registrations and supplied task/cohort selections |
| scripts/ | Numerical reproduction, log acquisition, parsing, and experiment launchers |
| data/logs/ | Logs grouped into 14 empirical-method collections |
| data/controlled/ | Scored rows and controlled-experiment summaries |
| results/ | Supplied analysis tables and figures |
| third_party/ | Pinned upstream source material and retained licenses |
| tests/ | Offline unit, boundary, ablation, and integration tests |
| docs/paper_map.csv | Paper section/table/figure to code and evidence mapping |
| docs/data_and_analysis.md | Data units, estimators, logs, and acquisition commands |
| docs/experiment_protocol.md | Experiment planning and explicit execution instructions |
| docs/third_party_sources.md | Exact upstream commits, reuse scope, and source notices |

Project Python filenames use English lower_snake_case. Source identifiers
inside supplied records remain stable join keys. Third-party attribution and
upstream license notices are retained instead of being renamed as our work.

## Exact ablation contract

| Condition | Enabled modules | Controller |
|---|---|---|
| full_audit | All seven | Full |
| minus_grounding | All except grounding | Full |
| minus_ownership | All except ownership | Full |
| minus_contradiction | All except contradiction | Full |
| minus_detour | All except detour | Full |
| minus_path_verification | All except path verification | Full |
| minus_memory | All except memory | Full |
| minus_abstention | All except abstention | Full |
| majority_controller | All seven, same outputs | Majority aggregation |

The matrix computes module outputs once for a fixed model-facing snapshot.
Each removal filters only the named output before aggregation. Other module
outputs, the snapshot, model metadata, and configuration parameters stay fixed.
The majority condition changes only aggregation. It uses equally weighted
module ballots with an explicit plurality/tie rule and separately reports
whether the winner has a strict majority.

The full controller applies configured enabled-module vetoes and evidence
precedence. Memory retains source-referenced evidence within a task/trial; it
never learns from gold localization or final repair labels. Module definitions,
thresholds, tie rules, and quality normalizers are explicit artifact parameters
in configs/conditions, not inferred from outcome tables.

## Run AUDIT on model-facing evidence

A snapshot contains task/trial identifiers, issue/context, candidate files,
evidence references, chronological tool/history events, repository inventory,
and model metadata. The full typed contract is in src/audit_framework/schema.py.
Gold files, benchmark patches, post-hoc labels, and final repair outcomes are
not accepted as model-facing inputs.

~~~sh
audit-framework validate --snapshot my_snapshot.json
audit-framework evaluate --snapshot my_snapshot.json --condition full_audit --out outputs/full_audit.json
audit-framework ablate --snapshot my_snapshot.json --out outputs/component_grid.json
~~~

Output includes enabled/disabled module sets, module-level evidence and
verdicts, exact snapshot/output digests, controller decisions, canonical trace,
and the five separate process-quality dimensions. Unsupported dimensions are
null, not zero. Existing output files are not silently overwritten.

To build a snapshot from source files in a local checkout without model calls:

~~~sh
audit-framework inspect --repository path/to/checkout --task-id issue_001 --issue-file issue.txt --candidate package/module.py --out outputs/snapshot.json
~~~

The inspection tool is read-only and does not establish repair correctness.
Provider-driven execution and the fixed SWE-Agent integration are described
in docs/experiment_protocol.md and docs/third_party_sources.md. They are
separate from offline data analysis and require explicit execution parameters.

## Analyze the supplied data

~~~sh
python reproduce.py --out outputs/analysis
python -m pip install -r requirements.txt
python reproduce.py --out outputs/analysis --figures
~~~

The analysis reads existing measurements. It does not regenerate model
responses or benchmark outcomes. Numerical scripts use the standard library;
plotting additionally uses the pinned requirements. The supplied results are
not overwritten. See docs/data_and_analysis.md for estimands and denominators.

## Public log acquisition and source reuse

Per-object acquisition manifests provide source URLs and available SHA-256
checksums. Full public logs can be acquired with the explicit download command
in docs/data_and_analysis.md; unavailable objects remain unavailable rather
than becoming successful observations. Upstream projects, exact commits,
reused code, and retained license files are listed in docs/third_party_sources.md.

## Anonymous 
