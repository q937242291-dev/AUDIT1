# Third-party source integration

The source selection contains four official repositories, 21 byte-for-byte original files (130,738 bytes), and four complete MIT licenses. Files are pinned to full Git commits; every file's canonical raw URL, byte size, and SHA-256 is recorded in **third_party/sources.lock.json**. Original copyright notices and author attribution are preserved. No Git metadata, credentials, task datasets, model weights, or generated trajectories are included in this source selection.

## Pins and reuse

| Source | Full commit | License | Integration and actual reuse |
| --- | --- | --- | --- |
| [SWE-agent](https://github.com/SWE-agent/SWE-agent) [2] | 3ea751c087f32b16e039a2233dd6eefecef325d5 | [MIT](../third_party/swe_agent/LICENSE) | Original hook protocol, trajectory types, run/configuration entry points, and default configuration. AUDIT supplies a tested adapter for the original on_actions_generated callback. The offline test executes the original CombinedAgentHook dispatcher classes with annotation types supplied locally. A full installed SWE-agent is used for config validation and live attachment. |
| [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) | 04d809ceab9df28f9adaed044884180159172930 | [MIT](../third_party/mini_swe_agent/LICENSE.md) | Original DefaultAgent serializer as schema evidence; original utils/serialize.py is dynamically imported and its recursive_merge function is called by the mini trajectory adapter. |
| [SWE-bench Pro](https://github.com/scaleapi/SWE-bench_Pro-os) [6,7] | 66f92766bba642462d4bbe5479e83f91f9211862 | [MIT](../third_party/swe_bench_pro/LICENSE) | Original gather_patches_from_local is imported and called after input validation. Original v1 repair evaluator and image-URI helper are available for explicit grading delegation. The builder emits the evaluator's actual CLI options. |
| [CRITIC](https://github.com/microsoft/ProphetNet/tree/master/CRITIC) [30] | 5cf70eb41cdaa1d8faa3e1265d95ee5792d49a53 | [MIT](../third_party/critic/LICENSE) | Original program/QA critique implementations and their utility file are retained. build_critic_feedback adapts the program critique's Question → proposal → Execution → Output → critique layout to localization and recorded tool observations. This is adapted formatting, not execution of CRITIC's model/search/interpreter loop. |

The upstream context files are intentionally distinct from executable offline imports: only mini-swe-agent's serializer utility and Scale's prediction gatherer are imported by the stdlib adapters. The other selected source files define the interfaces and command protocols, or are explicit external harness entry points. The source slices are not standalone installations of their parent agent packages.

## Verify and acquire

From the source checkout, use Python 3.10+ for the offline adapters and Python 3.11+ for the pinned SWE-agent installation.

    python scripts/fetch_upstream_sources.py --verify
    python scripts/fetch_upstream_sources.py --fetch
    python -B -m unittest discover -s tests -p test_integrations.py -v

Verification is the default and needs no network. Fetching is explicit, bounded to the named source files, and uses HTTPS URLs containing full commits. Per-file acquisition is capped at 2 MiB and the total at 25 MiB. Downloads are staged in memory and checked against the lock before publication; modified local files are not overwritten. Retry URLs may append download=1 or raw=true to the same immutable raw URL. No package is installed and no downloaded program is launched by the fetcher.

Run the package from its source checkout (for example, an editable installation). The adapters locate third_party relative to that checkout. A standalone wheel needs the source selection packaged alongside it by the distributor.

## SWE-agent attachment before final localization

Paper §2.3.1 keeps the SWE-agent harness fixed while changing AUDIT module outputs or aggregation. The interface here attaches through the original **on_actions_generated(step=...)** hook. In the pinned official agent, this callback immediately precedes **handle_action(step)**. This is the point where the application must identify a final-localization action, construct its agent-visible snapshot, and apply the selected AUDIT decision.

Public Python interfaces:

    build_swe_agent_invocation(
        *, config, repository, issue_file, output_dir, model, cost_limit,
        commit=None,
    ) -> PinnedInvocation

    validate_swe_agent_config(config: dict) -> upstream RunSingleConfig

    attach_pre_final_audit(
        agent, snapshot_factory,
        *, is_final_action, apply_decision, condition='full_audit',
    ) -> PreFinalAuditHook

The invocation object exposes repository, commit, install_requirement, argv, config_sha256, and prompt_sha256. It checks local inputs and the fixed commit and constructs the upstream command; it does not launch anything. Keep its config, prompt, model, repository state, and cost limit fixed across component conditions. Trial output directories may differ. The main experiment orchestrator remains responsible for repository-state and matched-task registration.

The full upstream package can be installed explicitly into the harness environment with:

    python -m pip install "git+https://github.com/SWE-agent/SWE-agent.git@3ea751c087f32b16e039a2233dd6eefecef325d5"

The bare upstream command produced by the builder has this form:

    sweagent run --config harness.yaml --env.repo.path task_repo \
      --problem_statement.path issue.md --agent.model.name MODEL \
      --agent.model.per_instance_cost_limit BUDGET --output_dir runs/trial \
      --actions.open_pr=false --actions.apply_patch_locally=false

That command runs the upstream harness alone. Attach AUDIT through the Python lifecycle before calling run.run():

    from sweagent.run.run_single import RunSingle
    from audit_framework.integrations import (
        validate_swe_agent_config, attach_pre_final_audit,
    )

    validated = validate_swe_agent_config(harness_config)
    run = RunSingle.from_config(validated)
    hook = attach_pre_final_audit(
        run.agent,
        snapshot_factory=extract_agent_visible_snapshot,
        is_final_action=is_final_localization,
        apply_decision=apply_localization_decision,
        condition=condition_name,
    )
    # The application explicitly calls run.run() when executing a scheduled trial.

The three callbacks are required application interfaces:

| Callback | Contract |
| --- | --- |
| snapshot_factory(agent, step) | Returns a core snapshot dictionary: task_id, trial_id, issue/context, candidates, evidence, history, repository_files, model_config. The schema validates it before evaluation. Supply current agent-visible information only. |
| is_final_action(step) | Identifies the application's final-localization tool/action. There is no assumption that the standard repair submit action is a localization decision. |
| apply_decision(step, selected_result) | Applies selected_result['decision'] to the outgoing localization step before upstream dispatch. Synchronize step.action and any tool-call representation the application uses. Handle select, abstain, blocked and no_candidate explicitly. |

The hook calls **evaluate_conditions(snapshot)** once and keeps all nine results in **hook.records**. Only the chosen condition is passed to apply_decision. Its record schema is **{phase: 'before_final_localization', condition, results: {canonical_condition: core_result}}**. This records the shared snapshot/output digests produced by the core. A fresh run clears the hook records. The hook does not infer candidates from gold files, outcomes, or final grading records.

Attachment and upstream configuration validation require an installation whose direct_url.json attests the official repository and exact pinned commit. Configuration validation calls the original RunSingleConfig.model_validate; it does not start a model or container. The offline tests exercise the hook protocol using the original dispatcher and the real core engine, not a live model run.

## Canonical trajectories and offline CLI

    parse_trajectory(raw, *, source, task_id, trial_id='default')
        -> CanonicalTrajectory

    snapshot_from_trajectory(
        trajectory, *, before_index, candidates,
        issue='', repository_files=None, model_config=None,
    ) -> dict

Supported source names are swe_agent, swe_bench_pro, mini_swe_agent, and deepswe. SWE-agent/Pro inputs use a top-level trajectory array. Mini inputs use messages with mini-swe-agent-1.0 or 1.1 format; absent version means the older messages layout. The 1.1 action list under message.extra.actions and ordinary tool_calls are preserved. DeepSWE accepts that messages layout or ATIF-style steps, including structured observation.results and tool-call identifiers.

Canonical JSON fields:

| Object | Fields |
| --- | --- |
| Trajectory | task_id, trial_id, source, format, raw_count, events |
| Event | id, raw_index, role, context, action, observation, tool_call_id |

Caller-provided task/trial identifiers and raw record indices are retained exactly. Structured action/observation fields are serialized as deterministic JSON strings. Final summary/info/reward metadata is not mapped into agent-visible events. Parsing normalizes records; it does not compute paper process statistics or resolve outcomes.

The snapshot bridge requires an **exclusive raw-record cutoff** before the final localization record. Each preceding observation becomes unverified tool evidence named observation:INDEX. The caller explicitly links candidate evidence_refs to those identifiers. No process exit or benchmark success flag is converted into candidate correctness. Unknown trace formats and malformed records raise ValueError; terminal exit messages cannot be included in a snapshot prefix.

    python -m audit_framework.integrations parse \
      --trajectory trace.json --source swe_agent --task-id TASK --trial-id TRIAL

    python -m audit_framework.integrations audit-prefix \
      --trajectory trace.json --source swe_agent --task-id TASK --trial-id TRIAL \
      --before-index 12 --context agent_context.json

The context file contains candidates plus optional issue, repository_files and model_config. audit-prefix prints the core's dictionary of all nine condition results. It does not write empirical data or execute a model. The planning command also prints JSON without execution:

    python -m audit_framework.integrations swe-agent-plan \
      --config harness.yaml --repository task_repo --issue-file issue.md \
      --output-dir runs/trial --model MODEL --cost-limit BUDGET

## Tool feedback, memory and grading

**build_critic_feedback(question, proposal, ToolFeedback(...))** returns prompt, evidence, verifier and source attribution. ToolFeedback carries task_id, trial_id, evidence_id, tool_ref, command, observation and an optional observed exit_code. A zero/nonzero exit describes that tool process only. Evidence remains unverified with respect to localization correctness. No command, proposed code, search, or model is executed.

**select_task_memory(episodes, *, task_id, trial_id, before_index, limit=8)** selects already-supplied, evidence-backed summaries strictly earlier than the cutoff and within the same task and trial. Each episode has task_id, trial_id, event_index, summary and evidence_refs. It validates the information boundary and rejects duplicate episode keys. It does not generate summaries or train a memory policy.

**gather_pro_predictions(directory, *, model_name)** calls Scale's original helper and returns a list of **{instance_id, patch, prefix}** objects. One .pred file is required in each instance_* folder. Original dataset IDs are retained; ambiguous files, malformed JSON and duplicate IDs fail before gathering. The adapter supplies UTF-8 decoding at the helper's open boundary so non-ASCII patches are preserved across operating systems; the vendored file remains byte-identical. This function is evaluator-side and separate from the snapshot path.

**build_pro_evaluation_invocation(*, raw_sample_path, patch_path, scripts_dir, output_dir, dockerhub_username, num_workers=1, python='python')** returns repository, commit, protocol, argv and executed=false. It points at the original vendored v1 evaluator and includes --use_local_docker and --block_network. Explicit execution needs that evaluator's dependencies, Docker, the official v1 metadata, public task images, and matching official run_scripts from the same Pro repository pin. None is downloaded or invoked by the adapter tests. This v1 command is separate from Pro's v2 Harbor protocol.

## Additional official references

These sources are tracked in **third_party/reference_sources.json**; no code from them is included in the four-source selection.

- [DeepSWE](https://github.com/datacurve-ai/deep-swe) [9], commit 0b9fabbb63b9104d678fe965e1632f2dd9eaa2ea, Apache-2.0. Its official README describes mini-swe-agent via Pier and the task/verifier boundary. The included DeepSWE parser is original AUDIT code; the imported mini serializer utility is identified above.
- [Reflexion](https://github.com/noahshinn/reflexion) [47], commit 218cf0ef1df84b05ce379dd4a8e47f17766733a0, MIT. Verbal episodic feedback is an idea-level reference for the task-scoped memory adapter; no Reflexion source was copied.
- [HiAgent](https://github.com/HiAgent2024/HiAgent) [31], commit cebdd8e4eacec1a532ce2c0041db8902217b90ba. Official authors link this repository. No redistribution license was verified in the checked root license files, so its implementation is cited rather than copied. Hierarchical working memory is an idea-level reference.
- [AgeMem](https://github.com/y1y5/AgeMem) [32], commit 98f563f907d67b2f2436e3ae7b7ceff32e482814. This is the repository bearing the exact cited Agentic Memory title, not the separately named A-MEM project. No redistribution license was verified in the checked root license files; no code is copied. Unified memory management is an idea-level reference, not an implemented learned policy.

Source verification uses the official repository pages, their license files, and public Git HEAD resolution. No third-party mirror is used. GitHub API rate limiting was avoided by resolving public Git refs and acquiring commit-addressed raw files. The included source manifest records the immutable acquisition identities.
