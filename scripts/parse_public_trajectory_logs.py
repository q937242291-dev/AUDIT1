#!/usr/bin/env python3
"""Offline public trajectory parser; no model, evaluator, or network calls.

Classification functions below are recovered verbatim from the original DeepSWE
and SWE-bench Pro parsers. Provenance records their original SHA-256 hashes.
Outputs contain identifiers, counts and roles, never prompt/response excerpts.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import re
import sys
import unittest
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ROLES = ('issue_specification', 'repository_orientation', 'code_search',
         'direct_file_read', 'history_lookup', 'environment_setup',
         'dependency_or_network', 'edit_or_patch', 'test_or_build',
         'diff_validation', 'feedback_recovery', 'other_tool_step')
MAX_BYTES = 100_000_000

def compact_text(value: Any, limit: int = 900) -> str:
    parts: list[str] = []

    def visit(item: Any) -> None:
        if sum(len(part) for part in parts) >= limit:
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {"text", "message", "content", "output", "observation", "error", "role", "name", "command", "function_name"}:
                    visit(child)
                elif isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, (str, int, float, bool)):
            remaining = limit - sum(len(part) for part in parts)
            if remaining > 0:
                parts.append(str(item)[:remaining])

    visit(value)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()[:limit]

def tool_names(step: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for call in step.get("tool_calls", []) if isinstance(step.get("tool_calls"), list) else []:
        if isinstance(call, dict):
            name = call.get("function_name") or call.get("name") or call.get("tool_name")
            if name:
                names.append(str(name))
    return names

def role_for(tool_text: str, step_text: str) -> str:
    text = f"{tool_text} {step_text}".lower()
    if re.search(r"test|pytest|build|compile|lint|check", text): return "test_or_build"
    if re.search(r"git diff|diff --|status --porcelain|review diff", text): return "diff_validation"
    if re.search(r"apply_patch|git apply|edit|write|replace|patch", text): return "edit_or_patch"
    if re.search(r"grep|rg |ripgrep|search|find ", text): return "code_search"
    if re.search(r"read|cat |sed |head |tail |view|open file", text): return "direct_file_read"
    if re.search(r"git log|git blame|history|commit", text): return "history_lookup"
    if re.search(r"pip |npm |yarn |cargo |go mod|install|dependency|http|curl|wget", text): return "dependency_or_network"
    if re.search(r"docker|environment|venv|virtualenv|cd |pwd|which ", text): return "environment_setup"
    if re.search(r"issue|requirement|problem statement|task description", text): return "issue_specification"
    if re.search(r"error|failed|failure|traceback|retry|fix", text): return "feedback_recovery"
    return "other_tool_step"

def future_signal(text: str) -> bool:
    return bool(re.search(r"gold patch|reference patch|hidden test|future test|grader|test patch|expected fix", text.lower()))

def numeric(value: Any) -> Any:
    return value if isinstance(value, (int, float)) else ""

ROLE_ORDER = [
    "issue_specification",
    "repository_orientation",
    "code_search",
    "direct_file_read",
    "history_lookup",
    "environment_setup",
    "dependency_or_network",
    "edit_or_patch",
    "test_or_build",
    "diff_validation",
    "feedback_recovery",
    "other_tool_step",
]

FUTURE_GOLD_RE = re.compile(
    r"\b(gold\s+patch|reference\s+solution|ground[- ]truth\s+patch|future\s+commit|"
    r"test\s+patch|expected\s+diff|gold\s+diff|oracle\s+patch|upstream\s+fix)\b",
    re.I,
)

HISTORY_RE = re.compile(r"\bgit\s+(log|show|blame|reflog|bisect)\b", re.I)

NETWORK_RE = re.compile(r"\b(curl|wget|http://|https://|pip\s+install|npm\s+install|yarn\s+add|apt\s+install|conda\s+install)\b", re.I)

TEST_RE = re.compile(r"\b(pytest|py\.test|unittest|tox|nose|npm\s+(test|run)|yarn\s+test|mvn\s+(test|verify)|gradle\s+test|cargo\s+test|go\s+test|make\s+(test|check))\b", re.I)

SEARCH_RE = re.compile(r"\b(rg|ripgrep|grep|git\s+grep|find|locate|ack|ag)\b", re.I)

READ_RE = re.compile(r"\b(cat|head|tail|sed\s+-n|less|more|bat|read_file|open_file)\b", re.I)

EDIT_RE = re.compile(r"(apply_patch|git\s+apply|sed\s+-i|perl\s+-pi|\b(edit|write|modify)\b|>>|\btee\b)", re.I)

DIFF_RE = re.compile(r"\b(git\s+diff|diff\s+-|compileall|py_compile|syntax|lint)\b", re.I)

SETUP_RE = re.compile(r"\b(pip|virtualenv|venv|conda|poetry|npm|yarn|bundle|cargo|go\s+mod|make\s+build|setup|install)\b", re.I)

def preview(value: Any, limit: int = 4000) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    return text if len(text) <= limit else text[:limit] + "...[truncated; raw .traj is complete]"

def flatten_event(event: Any) -> tuple[str, str, str]:
    if isinstance(event, dict):
        action = event.get("action", event.get("command", event.get("tool", "")))
        observation = event.get("observation", event.get("output", event.get("result", "")))
        response = event.get("response", event.get("message", event.get("content", "")))
        thought = event.get("thought", event.get("analysis", ""))
        if isinstance(response, dict) and not thought:
            thought = response.get("thought", response.get("analysis", ""))
        return preview(action), preview(observation), preview(response if not thought else {"response": response, "thought": thought})
    return "", preview(event), ""

def classify(action: str, observation: str, response: str, index: int) -> str:
    text = " ".join([action, observation, response])
    if index == 0 and len(text) > 80 and not action:
        return "issue_specification"
    if HISTORY_RE.search(text):
        return "history_lookup"
    if EDIT_RE.search(text):
        return "edit_or_patch"
    if TEST_RE.search(text):
        return "test_or_build"
    if DIFF_RE.search(text):
        return "diff_validation"
    if NETWORK_RE.search(text):
        return "dependency_or_network"
    if SETUP_RE.search(text) and not SEARCH_RE.search(text):
        return "environment_setup"
    if SEARCH_RE.search(text):
        return "code_search"
    if READ_RE.search(text):
        return "direct_file_read"
    if re.search(r"(traceback|error:|failed|failure|non[- ]zero|returncode.{0,8}[1-9])", text, re.I) and re.search(r"(retry|again|adjust|fix|update|change|rerun)", text, re.I):
        return "feedback_recovery"
    if action or observation or response:
        return "repository_orientation" if index <= 2 else "other_tool_step"
    return "other_tool_step"


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, empty_fields):
    with Path(path).open('w', encoding='utf-8', newline='') as f:
        fields = list(dict.fromkeys(k for row in rows for k in row)) or empty_fields
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def truth(value):
    return str(value).lower().strip() in ('true','1','yes')


def identifier(value):
    if not value or not re.fullmatch(r'[A-Za-z0-9_.-]+', value) or value in ('.','..'):
        raise ValueError('unsafe or missing artifact identifier')
    return value


def artifact_name(row, dataset):
    if dataset == 'deepswe':
        return identifier(row['trial_name'])+'.json'
    return identifier(row['run_id'])+'/instance_'+identifier(row['instance_id'])+'.traj'


def selected(rows, dataset):
    if dataset == 'deepswe':
        return [r for r in rows if truth(r.get('passed',r.get('official_success',''))) and truth(r.get('has_trajectory',r.get('public_log_complete','')))]
    return [r for r in rows if r.get('benchmark','SWE-bench Pro') == 'SWE-bench Pro' and truth(r.get('official_resolved',''))]


def parse_payload(payload, row, dataset, digest, byte_count):
    if dataset == 'deepswe':
        if not isinstance(payload, dict) or not isinstance(payload.get('steps'),list):
            raise ValueError('top-level steps list missing')
        events, counts, future = [], Counter(), False
        for i, step in enumerate(payload['steps']):
            if not isinstance(step,dict):
                continue
            text = compact_text(step)
            role = role_for(' '.join(tool_names(step)),text)
            signal = future_signal(text)
            counts[role] += 1
            future = future or signal
            events.append(dict(trial_name=row['trial_name'],task_name=row['task_name'],event_index=len(events),step_index=i,role=role,future_gold_signal_present=signal))
        metrics=payload.get('final_metrics') if isinstance(payload.get('final_metrics'),dict) else {}
        summary=dict(benchmark='DeepSWE v1.1',model=row['model'],reasoning_effort=row['reasoning_effort'],config=row['config'],
                     trial_name=row['trial_name'],task_name=row['task_name'],official_success=True,official_success_marker='passed=true',
                     trajectory_url=row.get('trajectory_url',''),trajectory_sha256=digest,trajectory_bytes=byte_count,
                     public_log_complete=True,parse_status='parsed',trajectory_step_count=len(payload['steps']),event_count=len(events),
                     total_cost_usd=numeric(metrics.get('total_cost_usd')),total_prompt_tokens=numeric(metrics.get('total_prompt_tokens')),
                     total_completion_tokens=numeric(metrics.get('total_completion_tokens')),future_gold_signal_present=future)
    else:
        trajectory=payload if isinstance(payload,list) else None
        if isinstance(payload,dict):
            for k in ('trajectory','events','steps','messages'):
                if isinstance(payload.get(k),list):
                    trajectory=payload[k]
                    break
        if trajectory is None:
            raise ValueError('trajectory/events/steps/messages list missing')
        events,counts= [], Counter()
        for i,item in enumerate(trajectory):
            action,obs,response=flatten_event(item)
            role=classify(action,obs,response,i)
            text=' '.join([action,obs,response])
            counts[role]+=1
            events.append(dict(run_id=row['run_id'],instance_id=row['instance_id'],event_index=i,role=role,
                               future_gold_signal_present=bool(FUTURE_GOLD_RE.search(text)),
                               test_selection_signal=bool(TEST_RE.search(text)),network_signal=bool(NETWORK_RE.search(text))))
        summary=dict(benchmark='SWE-bench Pro',run_id=row['run_id'],model=row['model'],instance_id=row['instance_id'],
                     official_resolved=True,success_marker='resolved=true',source_url=row.get('source_url',''),
                     trajectory_sha256=digest,trajectory_bytes=byte_count,event_count=len(events),
                     future_gold_signal_present=any(e['future_gold_signal_present'] for e in events),
                     test_selection_signal_present=any(e['test_selection_signal'] for e in events),
                     network_signal_present=any(e['network_signal'] for e in events))
        summary.update({r+'_event_count':counts[r] for r in ROLES})
    summary.update({r+'_present':counts[r]>0 for r in ROLES})
    return summary,events


def compare_summary(actual,expected,dataset):
    fields=['event_count']+[r+'_present' for r in ROLES]+['future_gold_signal_present']
    if dataset=='deepswe':
        fields += ['trajectory_step_count','total_cost_usd','total_prompt_tokens','total_completion_tokens']
    differences=[]
    for field in fields:
        a,b=actual[field],expected[field]
        if field.endswith('_present'):
            match=truth(a)==truth(b)
        elif a=='' or b=='':
            match=str(a)==str(b)
        else:
            match=float(a)==float(b)
        if not match:
            differences.append(dict(artifact_id=actual.get('trial_name',actual.get('instance_id')),field=field,computed=a,archived=b))
    return differences


class ParserTests(unittest.TestCase):
    def test_deepswe_priority_preserved(self):
        self.assertEqual(role_for('', 'git diff test patch'), 'test_or_build')
        self.assertEqual(role_for('', 'git log'), 'history_lookup')
        self.assertEqual(role_for('', 'hello'), 'other_tool_step')
    def test_pro_priority_preserved(self):
        self.assertEqual(classify('git log','pytest','',5),'history_lookup')
    def test_compact_limit(self):
        self.assertEqual(len(compact_text({'text':'x'*1000})),900)
    def test_non_dict_step_skipped(self):
        row=dict(trial_name='t',task_name='x',model='m',config='c',reasoning_effort='h')
        s,e=parse_payload({'steps':['skip',{'content':'pytest'}]},row,'deepswe','0'*64,1)
        self.assertEqual((s['trajectory_step_count'],s['event_count']),(2,1))
        self.assertNotIn('text_excerpt',e[0])
    def test_traversal_rejected(self):
        for value in ('../secret','[LOCAL_DRIVE]/secret','a/b','..',''):
            with self.assertRaises(ValueError): identifier(value)
    def test_missing_success_not_selected(self):
        self.assertEqual(selected([{'has_trajectory':'True'}],'deepswe'),[])
    def test_schema_failure_not_empty_success(self):
        with self.assertRaises(ValueError): parse_payload({}, {}, 'deepswe','',0)
        with self.assertRaises(ValueError): parse_payload({}, {}, 'swebench-pro','',0)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',choices=('deepswe','swebench-pro'),default='deepswe')
    p.add_argument('--manifest',type=Path)
    p.add_argument('--raw-root',type=Path)
    p.add_argument('--archive',type=Path,help='read local ZIP members in place, never extract')
    p.add_argument('--out',type=Path)
    p.add_argument('--validate-summary',type=Path)
    p.add_argument('--limit',type=int)
    p.add_argument('--self-test',action='store_true')
    args=p.parse_args(argv)
    if args.self_test:
        return 0 if unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ParserTests)).wasSuccessful() else 1
    if not args.manifest or not args.out or bool(args.raw_root)==bool(args.archive):
        p.error('provide --manifest, --out, and exactly one of --raw-root / --archive')
    if args.out.resolve()==args.manifest.resolve().parent:
        p.error('output must differ from manifest directory')
    if args.limit is not None and args.limit<1:
        p.error('--limit must be positive')
    rows=selected(read_csv(args.manifest),args.dataset)
    rows=sorted(rows,key=lambda r:artifact_name(r,args.dataset))
    if args.limit is not None:
        rows=rows[:args.limit]
    if not rows:
        p.error('no explicitly successful eligible rows')
    reference={artifact_name(r,args.dataset):r for r in read_csv(args.validate_summary)} if args.validate_summary else {}
    archive=zipfile.ZipFile(args.archive) if args.archive else None
    members={i.filename:i for i in archive.infolist()} if archive else {}
    summaries,events,queue,mismatches=[],[],[],[]
    try:
        for row in rows:
            name=artifact_name(row,args.dataset)
            record=dict(artifact=name,source_url=row.get('trajectory_url',row.get('source_url','')))
            try:
                if archive:
                    member=('raw_trajectory_json/'+name) if args.dataset=='deepswe' else name.replace('/instance_','/success/instance_',1)
                    info=members.get(member)
                    if info is None: raise FileNotFoundError('archive member absent')
                    if info.file_size>=MAX_BYTES: raise ValueError('file exceeds strict 100MB limit')
                    data=archive.read(info)
                else:
                    raw=(args.raw_root/name).resolve()
                    if not raw.is_relative_to(args.raw_root.resolve()): raise ValueError('raw path escapes root')
                    if raw.stat().st_size>=MAX_BYTES: raise ValueError('file exceeds strict 100MB limit')
                    data=raw.read_bytes()
                digest=hashlib.sha256(data).hexdigest()
                expected=row.get('anonymized_sha256') or row.get('sha256') or row.get('trajectory_sha256')
                if expected and digest!=expected: raise ValueError('SHA-256 mismatch')
                payload=json.loads(data.decode('utf-8-sig',errors='strict' if args.dataset=='deepswe' else 'replace'))
                summary,ev=parse_payload(payload,row,args.dataset,digest,len(data))
                summaries.append(summary);events.extend(ev)
                if args.validate_summary:
                    if name not in reference:
                        mismatches.append(dict(artifact_id=name,field='reference',computed='parsed',archived='absent'))
                    else:
                        mismatches.extend(compare_summary(summary,reference[name],args.dataset))
            except (OSError,ValueError,KeyError,TypeError,UnicodeError) as exc:
                # Error types and static reasons only; no host paths or payload text.
                reason=str(exc) if isinstance(exc,ValueError) and str(exc) in ('SHA-256 mismatch','file exceeds strict 100MB limit','raw path escapes root','top-level steps list missing','trajectory/events/steps/messages list missing') else type(exc).__name__
                queue.append(dict(**record,status='not_parsed',reason=reason))
    finally:
        if archive: archive.close()
    args.out.mkdir(parents=True,exist_ok=True)
    write_csv(args.out/'success_trajectory_summary.csv',summaries,['artifact_id'])
    write_csv(args.out/'trajectory_event_index.csv',events,['artifact_id','event_index','role'])
    write_csv(args.out/'parse_queue.csv',queue,['artifact','source_url','status','reason'])
    write_csv(args.out/'reference_mismatches.csv',mismatches,['artifact_id','field','computed','archived'])
    result=dict(dataset=args.dataset,eligible_selected_rows=len(rows),parsed_rows=len(summaries),event_rows=len(events),
                queued_rows=len(queue),reference_checked=bool(args.validate_summary),reference_mismatches=len(mismatches),
                raw_payloads_copied=False,event_text_exported=False,network_calls=0,model_calls=0,
                manifest_sha256=hashlib.sha256(args.manifest.read_bytes()).hexdigest())
    (args.out/'parse_report.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
    return 2 if queue or mismatches else 0


if __name__=='__main__':
    raise SystemExit(main())

