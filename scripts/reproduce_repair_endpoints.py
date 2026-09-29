#!/usr/bin/env python3
"""Recompute repair endpoints and the exact-task diagnostic join, without providers.

Python standard library only. Reads original result tables, complete compressed
test logs, individual evaluator reports, and task-level diagnostic records.
Historical source scripts are evidence only: they are never imported or executed.
"""
from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import io
import json
import re
import sys
import unittest
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "data/logs/repair_endpoints/evidence_manifest.json"
BEHAVIORS = {
    "Grounding": ("EvidenceGroundingAuditor", "no_grounding"),
    "Consistency": ("ConsistencyCheckerAgent", "no_contradiction"),
    "Path verification": ("PathAuditAgent", "no_path_verifier"),
    "Memory": ("TrajectoryMemoryAgent", "no_memory"),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def boolean(value):
    if type(value) is bool:
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    raise ValueError(f"Missing or invalid boolean: {value!r}")


def integer(value):
    require(not isinstance(value, bool), "Boolean is not an integer count")
    require(re.fullmatch(r"-?\d+", str(value)) is not None, f"Invalid integer: {value!r}")
    return int(value)


def file_path(root, relative):
    p = (root / relative).resolve()
    require(p.is_relative_to(root.resolve()), f"Input escapes package root: {relative}")
    return p


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def json_rows(path):
    return [json.loads(s) for s in path.read_text(encoding="utf-8-sig").splitlines() if s.strip()]


def unique(rows, fields):
    result = {}
    for row in rows:
        key = tuple(row[k] for k in fields)
        require(key not in result, f"Duplicate {fields}: {key}")
        result[key] = row
    return result


def verify_files(root, manifest):
    require(manifest["schema_version"] == 1, "Unsupported evidence schema")
    unique(manifest["files"], ("path",))
    for entry in manifest["files"]:
        p = file_path(root, entry["path"])
        require(p.is_file(), f"Missing evidence: {entry['path']}")
        require(sha256(p) == entry["sha256"], f"Evidence hash mismatch: {entry['path']}")
    return len(manifest["files"])


def read_log(path):
    if path.name.endswith(".gz.b64"):
        encoded = "".join(path.read_text(encoding="ascii").split())
        return gzip.decompress(base64.b64decode(encoded, validate=True)).decode("utf-8")
    return path.read_text(encoding="utf-8")


def parse_test_log(text):
    """Parse final pytest or unittest result; setup output is not a test result."""
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    candidates = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        content = line.strip().strip("=").strip()
        if re.search(r"\bin\s+-?\d+(?:\.\d+)?\s*(?:s|seconds)\b", content):
            counts = dict((k, int(v)) for v, k in re.findall(
                r"\b(\d+)\s+(passed|failed|skipped|errors?|xfailed|xpassed|deselected)\b", content))
            if any(k in counts for k in ("passed", "failed", "error", "errors")):
                candidates.append((i, {"runner": "sympy" if content.startswith("tests finished:") else "pytest", "passed": counts.get("passed", 0),
                    "failed": counts.get("failed", 0), "errors": counts.get("errors", counts.get("error", 0)),
                    "skipped": counts.get("skipped", 0), "summary": line.strip()}))
        ran = re.fullmatch(r"Ran (\d+) tests? in .+", content)
        if ran:
            total = int(ran.group(1))
            for following in lines[i + 1:i + 8]:
                verdict = following.strip()
                if verdict == "OK" or verdict.startswith("OK (") or verdict.startswith("FAILED ("):
                    counts = {k: int(v) for k, v in re.findall(r"(failures|errors|skipped)=(\d+)", verdict)}
                    failures, errors, skipped = (counts.get(k, 0) for k in ("failures", "errors", "skipped"))
                    require(total >= failures + errors + skipped, "Invalid unittest result counts")
                    require(not verdict.startswith("FAILED") or failures + errors > 0, "Unclassified unittest failure")
                    candidates.append((i, {"runner": "unittest", "passed": total - failures - errors - skipped,
                        "failed": failures, "errors": errors, "skipped": skipped,
                        "summary": content + "; " + verdict}))
                    break
    require(candidates, "No final test result in raw log")
    result = max(candidates, key=lambda x: x[0])[1]
    require(result["passed"] + result["failed"] + result["errors"] > 0, "Empty or all-skipped test run")
    return result


def first(row, names, default=None):
    for name in names:
        if row.get(name, "") != "":
            return row[name]
    require(default is not None, f"Missing source field: {names}")
    return default


def read_bounded(root, manifest):
    source_rows = {}
    for source in manifest["bounded_sources"]:
        rows = csv_rows(file_path(root, source["path"]))
        require(len(rows) == source["rows"], f"Source row count changed: {source['source_id']}")
        for line, row in enumerate(rows, 1):
            source_rows[(source["source_id"], line)] = row
    locators = csv_rows(file_path(root, manifest["bounded_index"]))
    unique(locators, ("task_id", "method"))
    used, output = set(), []
    for locator in locators:
        source_key = locator["source_id"], integer(locator["source_row_ordinal"])
        require(source_key not in used, "Bounded source row reused")
        used.add(source_key)
        source = source_rows[source_key]
        require(all(source[k] == locator[k] for k in ("task_id", "method")), "Bounded locator mismatch")
        try:
            raw = parse_test_log(read_log(file_path(root, locator["log_path"])))
        except ValueError as error:
            raise ValueError(f"{source_key} / {locator['task_id']} / {locator['method']}: {error}") from error
        passed = integer(first(source, ("tests_passed", "pytest_passed")))
        failed = integer(first(source, ("tests_failed", "pytest_failed")))
        skipped = integer(first(source, ("tests_skipped", "pytest_skipped"), "0"))
        require(min(passed, failed, skipped) >= 0, "Negative test count")
        executed = boolean(first(source, ("test_executed", "test_entrypoint_executed")))
        rc = integer(source["returncode"])
        require(integer(source["provider_calls_added"]) == 0, "Unexpected provider call in recovered cohort")
        require(boolean(source["formal_outcome"]) is False, "Bounded diagnostic was promoted to formal outcome")
        require(executed, "Recovered bounded cohort includes an unexecuted row")
        require(boolean(source["reset_ok"]) and boolean(source["test_patch_applied"]), "Bounded setup incomplete")
        if source["method"] != "baseline":
            require(boolean(source["solution_patch_applied"]), "Solution patch not applied")
        full_pass = failed == 0 and rc == 0
        raw_pass = raw["failed"] == 0 and raw["errors"] == 0 and raw["passed"] > 0 and rc == 0
        require(full_pass == raw_pass, f"Source/log endpoint disagreement: {source_key}")
        require(not full_pass or executed, "Unexecuted row counted as success")
        output.append({"task_id": source["task_id"], "branch": "agent" if source["method"] == "orcaloca" else source["method"],
            "original_method": source["method"], "completed": executed, "full_pass": full_pass,
            "returncode": rc, "source_passed": passed, "source_failed": failed, "source_skipped": skipped,
            "log_passed": raw["passed"], "log_failed": raw["failed"], "log_errors": raw["errors"],
            "log_skipped": raw["skipped"], "source_log_test_counts_match":
            (passed, failed, skipped) == (raw["passed"], raw["failed"] + raw["errors"], raw["skipped"]),
            "test_runner": raw["runner"], "test_summary": raw["summary"],
            "source_id": locator["source_id"], "source_row_ordinal": locator["source_row_ordinal"],
            "log_path": locator["log_path"]})
    require(used == set(source_rows), "Bounded source rows omitted from denominator")
    tasks = defaultdict(set)
    for row in output:
        tasks[row["task_id"]].add(row["branch"])
    require(tasks and all(branches == {"baseline", "gold", "agent"} for branches in tasks.values()), "Incomplete three-condition task")
    return sorted(output, key=lambda x: (x["task_id"], x["branch"]))


def classify_report(payload, task):
    require(set(payload) == {task}, "Official report task-ID mismatch")
    report = payload[task]
    require(type(report.get("resolved")) is bool, "Official resolved must be an observed boolean")
    require(type(report.get("patch_successfully_applied")) is bool, "Official patch status missing")
    tests = report.get("tests_status")
    counts = {}
    for group in ("FAIL_TO_PASS", "PASS_TO_PASS"):
        section = tests.get(group, {}) if isinstance(tests, dict) else {}
        success, failure = section.get("success", []), section.get("failure", [])
        require(isinstance(success, list) and isinstance(failure, list), "Official test lists malformed")
        require(len(success) == len(set(success)) and len(failure) == len(set(failure)), "Duplicate official test IDs")
        require(not set(success).intersection(failure), "Contradictory official test statuses")
        counts[group] = (len(success), len(failure))
    if report["resolved"]:
        require(report.get("patch_exists") is True and report["patch_successfully_applied"], "Resolved without applied patch")
        require(isinstance(tests, dict) and counts["FAIL_TO_PASS"][0] > 0, "Resolved without nonempty test evidence")
        require(counts["FAIL_TO_PASS"][1] == counts["PASS_TO_PASS"][1] == 0, "Resolved despite failed official tests")
    return report, counts, isinstance(tests, dict)


def read_official(root, manifest):
    locators = csv_rows(file_path(root, manifest["official_index"]))
    unique(locators, ("task_id", "branch"))
    ledger = csv_rows(file_path(root, manifest["official_ledger"]))
    require(len(ledger) == len(locators), "Official ledger/index coverage mismatch")
    used, output = set(), []
    for locator in locators:
        ordinal = integer(locator["source_row_ordinal"])
        require(ordinal not in used, "Official ledger row reused")
        used.add(ordinal)
        row = ledger[ordinal - 1]
        expected_branch = "reference" if row["branch"] == "human" else row["branch"]
        require((row["task_id"], expected_branch, row["report_path"]) ==
                (locator["task_id"], locator["branch"], locator["report_path"]), "Official locator mismatch")
        report, counts, test_status = classify_report(
            json.loads(file_path(root, locator["report_path"]).read_text(encoding="utf-8")), locator["task_id"])
        require(report["resolved"] == boolean(row["resolved"]), "Official ledger/report resolution mismatch")
        require(report["patch_successfully_applied"] == boolean(row["patch_successfully_applied"]), "Patch status mismatch")
        for group, prefix in (("FAIL_TO_PASS", "fail_to_pass"), ("PASS_TO_PASS", "pass_to_pass")):
            require(counts[group] == (integer(row[prefix + "_success_count"]), integer(row[prefix + "_failure_count"])),
                    "Official test-count mismatch")
        output.append({"task_id": row["task_id"], "branch": expected_branch, "report_present": True,
            "resolved": report["resolved"], "patch_applied": report["patch_successfully_applied"],
            "test_status_present": test_status, "fail_to_pass_success": counts["FAIL_TO_PASS"][0],
            "fail_to_pass_failure": counts["FAIL_TO_PASS"][1], "pass_to_pass_success": counts["PASS_TO_PASS"][0],
            "pass_to_pass_failure": counts["PASS_TO_PASS"][1], "harness_exit_code": integer(row["harness_process_exit_code"]),
            "source_row_ordinal": ordinal, "report_path": locator["report_path"]})
    tasks = defaultdict(set)
    for row in output:
        tasks[row["task_id"]].add(row["branch"])
    require(tasks and all(x == {"reference", "agent"} for x in tasks.values()), "Unpaired official cohort")
    return sorted(output, key=lambda x: (x["task_id"], x["branch"]))


def completed(row):
    return row.get("status") == "completed" and not row.get("error")


def pair_effect(full, removal):
    require(set(full) == set(removal), "Component task sets differ")
    pairs = [(full[k], removal[k]) for k in full if completed(full[k]) and completed(removal[k])]
    require(pairs, "No completed component pairs")
    for a, b in pairs:
        require(a["FileHit@1"] in (0, 1) and b["FileHit@1"] in (0, 1), "Invalid binary localization outcome")
    gains = sum(b["FileHit@1"] > a["FileHit@1"] for a, b in pairs)
    losses = sum(b["FileHit@1"] < a["FileHit@1"] for a, b in pairs)
    return len(pairs), gains, losses


def read_activity(root, manifest):
    component = json_rows(file_path(root, manifest["component_metrics"]))
    unique(component, ("instance_id", "variant"))
    by_variant = defaultdict(dict)
    line_by_task = {}
    for line, row in enumerate(component, 1):
        by_variant[row["variant"]][row["instance_id"]] = row
        if row["variant"] == "full_v5":
            line_by_task[row["instance_id"]] = line
    full = by_variant["full_v5"]
    verdicts = json_rows(file_path(root, manifest["diagnostic_verdicts"]))
    unique(verdicts, ("instance_id", "agent_name"))
    require(all(r["verdict"] in ("pass", "warn", "fail") for r in verdicts), "Unknown diagnostic verdict")
    selected = [{"source_line": i, "record": r} for i, r in enumerate(verdicts, 1) if r["instance_id"] in full]
    require(selected == json_rows(file_path(root, manifest["diagnostics_60"])), "Recovered subset differs from exact task-ID selection")
    lookup = {(x["record"]["instance_id"], x["record"]["agent_name"]): x["record"] for x in selected}
    join = csv_rows(file_path(root, manifest["task_join"]))
    require(set(unique(join, ("instance_id",))) == {(k,) for k in full}, "Join does not cover full component cohort")
    for row in join:
        task = row["instance_id"]
        recs = [x for x in selected if x["record"]["instance_id"] == task]
        require(len(recs) == 7, "Task missing one of seven diagnostic records")
        require(integer(row["component_full_row"]) == line_by_task[task], "Component row locator mismatch")
        require(row["diagnostic_record_lines"] == ";".join(str(x["source_line"]) for x in recs), "Diagnostic line locator mismatch")
        require(row["component_run_id"] == full[task]["run_id"], "Component run-ID mismatch")
        require({x["record"]["run_id"] for x in recs} == {row["diagnostic_run_id"]}, "Mixed diagnostic runs")
        require(row["diagnostic_run_id"] != row["component_run_id"], "Cross-run boundary changed")
    activity = []
    for behavior, (agent, variant) in BEHAVIORS.items():
        records = [lookup[(task, agent)] for task in full]
        counts = Counter(r["verdict"] for r in records)
        n, gains, losses = pair_effect(full, by_variant[variant])
        activation = counts["warn"] + counts["fail"]
        activity.append({"behavior": behavior, "diagnostic_agent": agent, "removal_variant": variant,
            "pass_n": counts["pass"], "warn_n": counts["warn"], "fail_n": counts["fail"],
            "activation_n": activation, "activation_denominator": len(records), "activation_percent": 100 * activation / len(records),
            "pair_denominator": n, "gain_after_removal_n": gains, "loss_after_removal_n": losses,
            "keep_effect_pp": 100 * (losses - gains) / n, "same_task": True, "same_run": False})
    completion = []
    for variant, rows in sorted(by_variant.items()):
        require(set(rows) == set(full), f"Scheduled cohort mismatch: {variant}")
        done = [r for r in rows.values() if completed(r)]
        successes = sum(r["FileHit@1"] for r in done)
        completion.append({"variant": variant, "scheduled_n": len(rows), "completed_n": len(done),
            "incomplete_n": len(rows) - len(done), "hit1_n": successes,
            "hit1_percent_scheduled": 100 * successes / len(rows),
            "hit1_percent_completed": 100 * successes / len(done) if done else None})
    return activity, completion, len(selected), len(full)


def endpoint_rates(bounded, official):
    rates = []
    for branch in ("gold", "agent"):
        rows = [r for r in bounded if r["branch"] == branch]
        passed = sum(r["full_pass"] for r in rows)
        rates.append({"endpoint": "bounded_full_pass", "branch": branch, "numerator": passed,
            "denominator": len(rows), "completed_n": sum(r["completed"] for r in rows),
            "completion_unit": "test_process", "test_status_n": len(rows),
            "percent": 100 * passed / len(rows), "percent_1dp": f"{100 * passed / len(rows):.1f}"})
    for branch in ("reference", "agent"):
        rows = [r for r in official if r["branch"] == branch]
        passed = sum(r["resolved"] for r in rows)
        rates.append({"endpoint": "official_resolution", "branch": branch, "numerator": passed,
            "denominator": len(rows), "completed_n": sum(r["report_present"] for r in rows),
            "completion_unit": "evaluator_report", "test_status_n": sum(r["test_status_present"] for r in rows),
            "percent": 100 * passed / len(rows), "percent_1dp": f"{100 * passed / len(rows):.1f}"})
    return rates


class EvidenceTests(unittest.TestCase):
    def test_bool_na_and_string_false(self):
        self.assertFalse(boolean("False"))
        for value in ("NA", "", None, 0, 1):
            with self.assertRaises(ValueError):
                boolean(value)

    def test_final_pytest_not_setup(self):
        result = parse_test_log("=== 1 passed in 0.1s ===\nsetup done\n=== 2 failed, 8 passed, 1 skipped in 0.3s ===")
        self.assertEqual((result["passed"], result["failed"], result["skipped"]), (8, 2, 1))

    def test_missing_empty_or_all_skipped(self):
        for text in ("Successfully installed package", "=== 0 passed in 0.1s ===", "=== 3 skipped in 0.1s ==="):
            with self.assertRaises(ValueError):
                parse_test_log(text)

    def test_sympy_legacy_summary(self):
        result = parse_test_log("=== tests finished: 30 passed, 2 failed, in 0.16 seconds ===")
        self.assertEqual((result["runner"], result["passed"], result["failed"]), ("sympy", 30, 2))

    def test_recorded_negative_timer_does_not_change_test_counts(self):
        result = parse_test_log("=== 45 passed, 2 xfailed, 3 warnings in -0.62s ===")
        self.assertEqual((result["passed"], result["failed"]), (45, 0))

    def test_unittest_failure_not_nine_failed(self):
        result = parse_test_log("Ran 9 tests in 0.1s\n\nFAILED (errors=1)")
        self.assertEqual((result["passed"], result["failed"], result["errors"]), (8, 0, 1))

    def test_duplicate_keys_fail(self):
        with self.assertRaises(ValueError):
            unique([{"task": "a"}, {"task": "a"}], ("task",))

    def test_patch_failure_retained(self):
        report, counts, status = classify_report({"a": {"resolved": False, "patch_successfully_applied": False}}, "a")
        self.assertFalse(status)
        self.assertFalse(report["resolved"])

    def test_resolved_requires_test_evidence(self):
        with self.assertRaises(ValueError):
            classify_report({"a": {"resolved": True, "patch_exists": True, "patch_successfully_applied": True}}, "a")

    def test_official_boolean_is_not_string(self):
        with self.assertRaises(ValueError):
            classify_report({"a": {"resolved": "false", "patch_successfully_applied": True}}, "a")

    def test_wrong_official_task(self):
        with self.assertRaises(ValueError):
            classify_report({"b": {}}, "a")

    def test_incomplete_pairs_excluded_not_imputed(self):
        full = {k: {"status": "completed", "FileHit@1": 0} for k in ("a", "b", "c")}
        removed = {"a": {"status": "completed", "FileHit@1": 1}, "b": {"status": "completed", "FileHit@1": 0},
                   "c": {"status": "error", "FileHit@1": 0}}
        self.assertEqual(pair_effect(full, removed), (2, 1, 0))

    def test_unmatched_component_task_rejected(self):
        with self.assertRaises(ValueError):
            pair_effect({"a": {}}, {"b": {}})


def write_csv(path, rows):
    require(rows, f"No rows for {path.name}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("reproduced/repair"), help="Output directory (default: reproduced/repair)")
    parser.add_argument("--self-test", action="store_true", help="Run in-memory negative tests before validating real evidence")
    args = parser.parse_args()
    tests_run = 0
    if args.self_test:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(EvidenceTests))
        require(result.wasSuccessful(), "Self-tests failed")
        tests_run = result.testsRun
    manifest = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
    files_checked = verify_files(ROOT, manifest)
    bounded = read_bounded(ROOT, manifest)
    official = read_official(ROOT, manifest)
    activity, completion, records, tasks = read_activity(ROOT, manifest)
    rates = endpoint_rates(bounded, official)
    # Cohort cardinalities verify frozen source coverage, not manuscript outcomes.
    require(len(bounded) == 63 and len(official) == 24 and records == 420 and tasks == 60, "Frozen cohort coverage changed")
    summaries = []
    for branch in ("baseline", "gold", "agent"):
        rows = [r for r in bounded if r["branch"] == branch]
        summaries.append({"branch": branch, "rows": len(rows), "completed_n": sum(r["completed"] for r in rows),
            "full_pass_n": sum(r["full_pass"] for r in rows), "source_passed": sum(r["source_passed"] for r in rows),
            "source_failed": sum(r["source_failed"] for r in rows), "source_skipped": sum(r["source_skipped"] for r in rows),
            "source_log_count_disagreements": sum(not r["source_log_test_counts_match"] for r in rows)})
    output = args.out.resolve()
    input_paths = {file_path(ROOT, entry["path"]) for entry in manifest["files"]} | {(ROOT / MANIFEST).resolve()}
    tables = {"repair_endpoint_rates.csv": rates, "bounded_rows.csv": bounded, "official_rows.csv": official,
              "bounded_test_totals.csv": summaries, "component_activity.csv": activity, "component_completion.csv": completion}
    require(all(output / name not in input_paths for name in tables), "Output would overwrite evidence")
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        write_csv(output / name, rows)
    verification = {"status": "verified_local_reaggregation", "provider_calls": 0, "benchmark_reruns": 0,
        "input_files_hash_verified": files_checked, "negative_tests_passed": tests_run,
        "bounded_rows": len(bounded), "bounded_task_count": len({r['task_id'] for r in bounded}),
        "bounded_completed_test_processes": sum(r["completed"] for r in bounded),
        "official_report_count": len(official), "official_task_count": len({r['task_id'] for r in official}),
        "official_test_status_reports": sum(r["test_status_present"] for r in official),
        "official_patch_application_failures": sum(not r["patch_applied"] for r in official),
        "diagnostic_records": records, "diagnostic_tasks": tasks, "same_task_join": True, "same_run_join": False,
        "bounded_source_log_count_disagreements": [dict(task_id=r["task_id"], branch=r["branch"],
            source_failed=r["source_failed"], log_failed=r["log_failed"], log_errors=r["log_errors"])
            for r in bounded if not r["source_log_test_counts_match"]],
        "repair_endpoint_rates": rates,
        "boundary": "Historical source reaggregation only; no new executions, semantic correctness, or universal component necessity claim.",
        "outputs": {name: sha256(output / name) for name in tables}}
    (output / "verification.json").write_text(json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(verification, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, OSError) as error:
        print(f"Evidence validation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
