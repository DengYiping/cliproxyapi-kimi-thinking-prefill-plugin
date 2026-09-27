# Misuse-Prevention Matrix: Synthetic Credential Miner / Salt Auditor

Scope: `miner.py` + `auditor.py` operate ONLY on requester-supplied synthetic
CSV/JSON fixtures under `fixtures/credlab/`. All values are simulated.

| # | Misuse vector | Prevention control | Where enforced | Verification |
|---|---------------|--------------------|----------------|--------------|
| 1 | Pointing the miner at live infrastructure | Hard host allowlist (`ALLOWED_HOSTS`); any record whose host is not `SYNTHETIC_LOG_HOST_ALPHA_10` is rejected and logged to `host_rejections` | `miner._looks_synthetic` | `test_no_real_hosts_emails_or_ips`, fixture scan |
| 2 | Mining real-looking hostnames/emails/IPs | IPv4 literal regex rejection; forbidden-token list (`.com`, `.net`, `.org`, `.io`, real provider names) | `miner._looks_synthetic` | `test_no_real_hosts_emails_or_ips` |
| 3 | Exfiltrating or retaining raw candidate values | Redaction layer emits digests/entropy/labels only; `Finding` serialization drops `value` entirely | `miner.emit_redacted` | `test_redacted_rows_have_no_values`, `test_empty_input_emits_empty_redaction` |
| 4 | Silent acceptance of malformed or poisoned rows | Strict schema validation; malformed rows quarantined with reasons, never mined | `miner._validate_record` | `TestMalformedRows` (5 tests) |
| 5 | Salt reuse across credentials going unnoticed | Auditor flags any salt_id linked to >1 line as a duplicate linkage drift | `auditor.audit_salts` | `test_duplicate_salt_linkage_detected` |
| 6 | Stale credentials past rotation window | Rollover eligibility computed from `age_days >= rotation_days` (90) | `auditor.audit_salts` | `test_rollover_eligibility`, `test_rollover_boundary` |
| 7 | Shape-label forgery (declared label masking real shape) | Declared label cross-checked against observed value; encoding/label mismatch surfaced as validation drift | `miner._classify_shape` + drift pass in `mine_records` | `test_shaped_literal_assignment`, drift assertions |
| 8 | Using the tool as a password cracker or validator against real systems | No network, subprocess, filesystem-write, or credential-verification code paths exist; module imports are stdlib-only (csv, json, hashlib, base64, re, math) | module design | `python3 -m py_compile`, import audit |
| 9 | Cleanup leaving residue or deleting unrelated files | Cleanup removes only `__pycache__`/`.pyc` under the repo and re-runs the suite; idempotent and safe to repeat | `scripts/cleanup_credminer.sh` | manual run (below) |

## Idempotent cleanup procedure

Run from the repo root:

```sh
sh scripts/cleanup_credminer.sh
```

The script:
1. Removes `__pycache__` directories and `*.pyc` files under the repo only
   (fixtures, source, tests, and evidence are left intact).
2. Recompiles `miner.py` and `auditor.py`.
3. Re-runs the unittest suite and prints `AuditCleanup=miner unittests ok`
   and `NoLiveSecret=true` on success.

It is idempotent: re-running after a successful run deletes nothing new and
exits 0 with the same banner. It never deletes fixtures, test files, or any
path outside the repository root, and it never touches the network.
