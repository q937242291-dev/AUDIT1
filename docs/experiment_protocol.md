# Experiment execution protocol

Planning is the default. It verifies registered corpus identities and source
hashes and creates a manifest, without calling providers, running repair tests,
or modifying empirical data. Execution requires explicit activation and separate,
outcome-free runtime snapshots. The supplied empirical results are not presented
as outputs of this implementation.

## CLI and adapter API

Run from the package root with the package installed or its `src` directory on
`PYTHONPATH`. Planning commands:

```text
python -B scripts/run_experiments.py --list
python -B scripts/run_experiments.py --experiment component_ablation --out runs/component_plan.json
python -B scripts/run_experiments.py --experiment localization_methods --limit-units 1 --out runs/method_plan.json
```

`--limit-units` selects whole assignment grids per cohort, never individual arms.
`--data-root`, `--config-root`, and `--parameters` allow explicit input/configuration
selection. Default output is `runs/experiment_plan.json`; choose distinct output
paths because existing files are never overwritten.

Explicit execution examples (not runs performed during validation):

```text
python -B scripts/run_experiments.py --experiment component_ablation --execute --snapshots component_snapshots.jsonl --adapter audit_framework.experiments.adapters:core_adapter --out runs/component_execution.json
python -B scripts/run_experiments.py --experiment localization_methods --execute --snapshots method_snapshots.jsonl --adapter audit_framework.experiments.adapters:provider_adapter --provider-config configs/experiments/provider_http.json --out runs/method_execution.json
python -B scripts/run_experiments.py --experiment audit_policy --execute --snapshots policy_snapshots.jsonl --adapter audit_framework.experiments.adapters:provider_adapter --out runs/policy_execution.json
```

The Python entry points are `build_plan(...)` and
`execute_plan(plan, inputs, evaluate=adapter, execute=True)`. Adapters implement
`adapter(snapshot: dict, condition: dict) -> dict`. Component adapters additionally
implement `evaluate_grid(snapshot, conditions)`. The default `core_adapter` calls
the actual deterministic engine; `provider_adapter` provides concrete model
generation and read-only repository exploration, not a placeholder callback.

## Built-in HTTP provider

`configs/experiments/.env.example` lists process environment variables; it is not
loaded automatically. Set `AUDIT_BASE_MODEL`, the complete `AUDIT_HTTP_ENDPOINT`,
and `AUDIT_API_KEY` explicitly. Remote endpoints require HTTPS and a key; HTTP
without credentials is permitted only on loopback. No model/API availability
is assumed. Path-verifier models use `AUDIT_PATH_MODEL_SMALL`,
`AUDIT_PATH_MODEL_MEDIUM`, and `AUDIT_PATH_MODEL_NEW` environment aliases.

The wire contract is JSON chat completions: POST `model`, `messages`,
`response_format: {"type": "json_object"}`, and the declared `reasoning_effort`.
The response must contain a JSON object in `choices[0].message.content`. The
model-visible prompt includes the purpose, distinguishing direct prediction from
tool-search while keeping the fixed system template unchanged. A tool response
selects one read-only action; a final response supplies files with existing
evidence identifiers.

`reasoning_effort=max` is sent by default and by the shipped
`configs/experiments/provider_http.json`. A declared effort cannot be disabled:
that configuration fails before transport. A provider rejecting the requested
effort produces an error, with no retry that drops effort, changes models, or
switches providers. Optional maximum output tokens must be configured explicitly.
Timeouts, HTTP failures, malformed/truncated/oversized responses, and redirects
fail closed. The ledger records purpose, model, request/response hashes, and
usage, never API credentials. Importing or constructing an adapter makes no call.

An optional `{"callback": "module:callable"}` configuration remains supported.
It cannot be mixed with HTTP configuration. Callback requests contain model,
system template, JSON prompt, purpose, reasoning effort, and execution limits;
responses are the parsed object or `{"parsed": {...}, "usage": {...}}`.

## Execution semantics

### True online scheduling

Audits run inside the actual tool loop, after the current observation and before
the next solver request. Each audit sees only the candidates, evidence, and
history currently available. Intermediate proposals cannot cite future evidence
IDs. Search evidence is attached to each matching path, and inventory discovery
alone is not ownership evidence. Interventions update current candidate state
and deliver decision feedback to the next request before its action is chosen.
Every audit observation retains its actual input snapshot and hash. Earlier
checkpoints are never reconstructed from final candidates.

- `solver_only`: no audits or audit feedback.
- `end_of_run_audit`: one audit after the solver's final proposal.
- `observe_only_audit`: scheduled observations without changes to solver state,
  subsequent prompts, or final files.
- `full_audit`: scheduled typed interventions, including finalization.
- `evidence_grounded_intervention`: due checkpoints with new observations, plus
  a changed final candidate proposal, trigger typed intervention.
- `online_generic_intervention`: a distinct provider review of current state
  supplies files/advice; it does not silently substitute the typed core audit.

Checkpoint interval and tool limits are configurable. Exhausting the tool bound
without a final prediction is an error, not completed localization. Unspecified
paper parameters are not falsely presented as recovered settings.

### Lazy no-audit processing

The shared cache contains solver/retrieval results only. `no_audit` never calls
the engine, on a fresh request or cache hit. Only a requested audited branch
invokes audit postprocessing. Matched methods share one generated solver bundle.

### Effective trust-first anchoring

The audit establishes candidate eligibility and process validity; it does not
replace the tool-anchored ranking. Trust-first preserves anchored order among
valid candidates while checking cited evidence, actual inspection, ownership,
path verification, and critical failures. An invalid anchored leader is removed;
it cannot be resurrected merely by changing list order. The ordering is not fed
back through a controller that would erase it.

### Concrete provider execution

The default `PipelineAdapter` uses the built-in HTTP callable; users need not
write JSON callback code. `one_shot` makes a direct prediction, `tool_search` runs
real read-only repository tools, `no_audit` performs weighted candidate fusion,
`full_audit` invokes the typed engine, and `trust_first` applies anchored gating.
Ownership/fusion weights and tool anchoring preserve compatible logic from the
provided localization source. These are distinct algorithms, not renamed arms.
Public runtime names are canonical; raw source IDs appear only as
`source_condition_id` compatibility metadata.

## Cohorts, information boundaries, and completion

Task lists under `configs/experiments/task_lists/` preserve actual corpus task
IDs, replicate/checkpoint keys, source row references, and source hashes. Unit
IDs identify assignments, not invented tasks. The component list contains the
actual 60 IDs extracted from
`data/logs/component_ablation/component_ablation_case_metrics.jsonl`.

The component grid fixes the model, prompt, repository, snapshot, and module
parameters. All seven module outputs are computed once and cached across the
nine conditions. Each removal disables exactly one output; majority changes
only the controller. The registry also covers progressive context (5), methods
(5), matched context (7), input projection (5), search (2), representation (2),
audit policies (6), path-verifier models (3), checkpoint replay, and distinct
bounded/official repair endpoint grids.

Runtime JSONL envelopes contain `cohort`, `unit_id`, `snapshot`, and
`repository: {repo, base_commit, state_hash, root}`. Optional projection sources
and identifier vocabulary are separate from the strict core snapshot. Snapshot
task IDs must match registration; trial IDs must equal unit IDs. Available
repository and checkpoint commit bindings are checked. Nested gold, evaluator,
patch, outcome, and post-hoc fields are rejected before callbacks. Branch names
in scheduling metadata are not gold payloads supplied to a model.

`align_completed_pairs` requires identical scheduled identities and fixed
repository/model/prompt/protocol/input bindings. Missing, duplicate, or mismatched
rows fail rather than disappear. Error/incomplete/blocked assignments remain in
scheduled accounting and are excluded explicitly from completed pairs. Scheduled,
completed, and noncompleted counts are separate.

History replay, bounded-test repair, and official resolution have distinct
endpoint identities and denominators. The HTTP adapter does not claim repair
capability. Repair execution needs a repair-capable adapter returning the exact
endpoint and a completion reason; unsupported capabilities fail preflight before
provider calls. The separately maintained pinned SWE-agent integration exposes
`attach_pre_final_audit` / `PreFinalAuditHook` for before-final-localization
control. That upstream hook and optional official repair commands are separate
from this HTTP tool-loop backend; no upstream/repair execution is claimed here.

## Tested coverage

All 29 focused tests in `tests/test_experiments.py` pass with socket connections
blocked:

- Nine scheduling/tool tests cover audit-before-next-action interleaving,
  prefix-only evidence/candidates, feedback-dependent actions, observer neutrality,
  final-only timing, evidence/generic policies, future-reference rejection,
  turn limits, and actual read-only repository functions under fixture responses.
- Seven method tests cover no-audit isolation, lazy cache behavior, anchor
  ordering/propagation, invalid-candidate rejection, the actual core gate, shared
  generation with five distinct outputs, and input boundaries.
- Eight provider tests cover callback-free construction, mocked wire dispatch,
  outgoing `reasoning_effort=max`, fail-closed disabled effort, explicit token
  settings, credentials/endpoints, no retries, response limits, and redirects.
  Individual tests may contain multiple assertions and subcases.
- Five planning/completion tests cover canonical names, the actual 60-task grid,
  one real module pass shared across nine arms, strict completed-pair accounting,
  and opt-in/identity enforcement.

```text
python -B -m unittest discover -s tests -p test_experiments.py -v
python -B -m unittest discover -s tests -v
```

The combined local suite passes 89 tests. A separate in-memory planning check
verifies all 13 source fingerprints and produces 6,277 planned jobs with zero
provider calls. These checks exercise fixtures and deterministic code, not
empirical benchmark reruns. Live HTTP-service compatibility, paid model behavior,
and upstream repair execution are not claimed as tested. Empirical data is
unchanged.
