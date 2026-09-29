#!/usr/bin/env python3
"""Offline plan by default; opt-in bounded public HEAD probes or downloads.
No provider keys, models or evaluators. HEAD availability does not verify bytes.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import re
import sys
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

ROOT=Path(__file__).resolve().parents[1]
HOSTS={'d3ujjcmjq6o8v6.cloudfront.net','scaleapi-results.s3.amazonaws.com'}


def truth(value):
    return str(value).strip().lower() in {'true','1','yes'}


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def public_url(url):
    p=urlsplit(url)
    if p.scheme!='https' or p.hostname not in HOSTS or p.username or p.password or p.query or p.fragment or p.port not in (None,443):
        raise ValueError('URL must be credential-free HTTPS on a documented source host')
    return url


def safe_id(value):
    if not value or not re.fullmatch(r'[A-Za-z0-9_.-]+',value) or value in ('.','..'):
        raise ValueError('unsafe artifact identifier')
    return value


def filename(row,dataset):
    if dataset=='deepswe': return safe_id(row['trial_name'])+'.json'
    return safe_id(row['run_id'])+'/instance_'+safe_id(row['instance_id'])+'.traj'


def selected_rows(manifest,limit=None,dataset='deepswe'):
    with Path(manifest).open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    if dataset=='deepswe':
        rows=[r for r in rows if truth(r.get('passed','')) and truth(r.get('has_trajectory',''))]
    else:
        rows=[r for r in rows if r.get('benchmark','SWE-bench Pro')=='SWE-bench Pro' and truth(r.get('official_resolved',''))]
    return rows if limit is None else rows[:limit]


class PublicRedirects(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        public_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


class FetchTests(unittest.TestCase):
    def test_credentials_rejected(self):
        for url in ('http://d3ujjcmjq6o8v6.cloudfront.net/a','https://u:p@d3ujjcmjq6o8v6.cloudfront.net/a','https://d3ujjcmjq6o8v6.cloudfront.net/a?token=secret','https://example.com/a'):
            with self.assertRaises(ValueError): public_url(url)
    def test_traversal_rejected(self):
        for name in ('../x','[LOCAL_DRIVE]/x','..',''):
            with self.assertRaises(ValueError): safe_id(name)
    def test_ids_preserved(self):
        self.assertEqual(filename({'trial_name':'task__Ab19'},'deepswe'),'task__Ab19.json')
    def test_no_success_inference(self):
        self.assertFalse(truth(''));self.assertFalse(truth('failed'))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',choices=('deepswe','swebench-pro'),default='deepswe')
    p.add_argument('--manifest',type=Path)
    p.add_argument('--output-root',type=Path)
    net=p.add_mutually_exclusive_group()
    net.add_argument('--download',action='store_true')
    net.add_argument('--probe',action='store_true',help='HEAD only, no integrity attestation')
    p.add_argument('--limit',type=int)
    p.add_argument('--timeout',type=float,default=20)
    p.add_argument('--max-file-mb',type=float,default=99)
    p.add_argument('--max-total-mb',type=float,default=100)
    p.add_argument('--overwrite',action='store_true')
    p.add_argument('--self-test',action='store_true')
    args=p.parse_args(argv)
    if args.self_test:
        return 0 if unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(FetchTests)).wasSuccessful() else 1
    if args.limit is not None and args.limit<1: p.error('--limit must be positive')
    if args.timeout<=0 or not 0<args.max_file_mb<100 or args.max_total_mb<=0:
        p.error('positive limits required; --max-file-mb must be strictly below 100')
    folder='deepswe_success_trajectories' if args.dataset=='deepswe' else 'swebench_pro_success_trajectories'
    base=ROOT/'data/logs'/folder
    manifest=args.manifest or base/('success_manifest.csv' if args.dataset=='deepswe' else 'acquisition_manifest.csv')
    out=args.output_root or base/'downloaded_trajectories'
    rows=selected_rows(manifest,args.limit,args.dataset)
    if not rows: p.error('no explicitly successful selected artifacts')
    report=[];used=0;opener=build_opener(PublicRedirects())
    if args.probe or args.download: out.mkdir(parents=True,exist_ok=True)
    for row in rows:
        url=row.get('trajectory_url') or row.get('source_url') or row.get('url','')
        expected=row.get('sha256') or row.get('trajectory_sha256') or ''
        record=dict(dataset=args.dataset,trial_name=row.get('trial_name',''),task_name=row.get('task_name',''),run_id=row.get('run_id',''),instance_id=row.get('instance_id',''),url=url,expected_sha256=expected,historical_status=row.get('status',row.get('historical_status','')),historical_http_status=row.get('http_status',row.get('historical_http_status','')),status='not_tested',sha256='',bytes_verified=False)
        partial=None
        try:
            public_url(url);name=filename(row,args.dataset);record['artifact']=name
            if not (args.download or args.probe): report.append(record);continue
            record['checked_at_utc']=datetime.now(timezone.utc).isoformat()
            target=(out/name).resolve()
            if not target.is_relative_to(out.resolve()): raise ValueError('path escapes root')
            if args.download and target.exists() and not args.overwrite:
                actual=digest(target)
                record.update(status='exists_hash_match' if expected and actual==expected else 'exists_hash_mismatch' if expected else 'exists_without_reference_hash',sha256=actual,bytes=target.stat().st_size,bytes_verified=bool(expected and actual==expected))
                report.append(record);continue
            req=Request(url,method='HEAD' if args.probe else 'GET',headers={'User-Agent':'observational-reproduction/1.0'})
            with opener.open(req,timeout=args.timeout) as response:
                public_url(response.url)
                record.update(http_status=response.status,final_url=response.url)
                length=response.headers.get('Content-Length')
                record['declared_bytes']=int(length) if length and length.isdigit() else None
                if args.probe:
                    record['status']='head_reachable'
                else:
                    ceiling=min(int(args.max_file_mb*1e6),int(args.max_total_mb*1e6)-used)
                    if ceiling<=0 or (record['declared_bytes'] is not None and record['declared_bytes']>ceiling):
                        record['status']='skipped_size_limit'
                    else:
                        target.parent.mkdir(parents=True,exist_ok=True)
                        with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.trajectory-',suffix='.part',delete=False) as f:
                            partial=Path(f.name);size=0
                            while True:
                                block=response.read(min(1024*1024,ceiling-size+1))
                                if not block: break
                                size+=len(block)
                                if size>ceiling: raise ValueError('size limit exceeded')
                                f.write(block)
                        used+=size;actual=digest(partial)
                        record.update(bytes=size,sha256=actual)
                        if expected and expected!=actual: record['status']='hash_mismatch'
                        elif record['declared_bytes'] is not None and size!=record['declared_bytes']: record['status']='size_mismatch'
                        else:
                            partial.replace(target);partial=None
                            record.update(status='downloaded_hash_match' if expected else 'downloaded_without_reference_hash',bytes_verified=bool(expected))
        except HTTPError as exc:
            record.update(status='http_error',http_status=exc.code,error_type=type(exc).__name__)
        except (URLError,TimeoutError,OSError,ValueError) as exc:
            record.update(status='failed',error_type=type(exc).__name__)
        finally:
            if partial is not None: partial.unlink(missing_ok=True)
        report.append(record)
    result=dict(dataset=args.dataset,manifest_sha256=digest(manifest),selected_rows=len(rows),mode='download' if args.download else 'HEAD_probe' if args.probe else 'offline_plan',transferred_bytes=used,network_requests_requested=bool(args.download or args.probe),model_calls=0,artifacts=report)
    if args.download or args.probe:
        (out/'fetch_report.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='artifacts'},indent=2))
    print(json.dumps({'status_counts':dict(Counter(r['status'] for r in report))},indent=2))
    return 2 if any(r['status'] in ('http_error','failed','hash_mismatch','size_mismatch','exists_hash_mismatch') for r in report) else 0


if __name__=='__main__':
    raise SystemExit(main())
