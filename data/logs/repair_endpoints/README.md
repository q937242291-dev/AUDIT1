# Recovered repair evidence

See `docs/repair_evidence.md` from the package root for source chains, denominator definitions, known count discrepancies, and reproduction instructions.

Run `python -B scripts/reproduce_repair_endpoints.py --self-test` from the package root. The default output is `reproduced/repair`. The checked-in local proof is under this directory's `reproduced/repair/` subtree. All processing is local and uses the Python standard library.

`evidence_manifest.json` hashes the input records. Historical source scripts are inspection-only text. Complete sanitized test logs are stored as gzip plus Base64 (`.gz.b64`); original private locations and original-byte hashes are kept outside the public package.
