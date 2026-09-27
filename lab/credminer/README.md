# Synthetic Credential-Shape Miner & Salting Auditor

Read-only analysis over a requester-supplied synthetic fixture. Operates on
`fixtures/synthetic_log.csv` and `fixtures/synthetic_log.json` only.

## Layout
- `miner.py` - parses CSV/JSON, verifies shape labels, classifies records
  (assignment / decoy / malformed), separates encoded vs salted candidates,
  computes SHA-256 with and without salt, emits redacted metadata.
- `auditor.py` - audits salt posture against designated parameters
  (salt_version=3, salt_id=salt_alpha_a, salt_target_length=24,
  rotation_days=90); flags duplicate linkage and rollover eligibility.
- `tests/test_miner_auditor.py` - 14 unittests.

## Fixture contract (7 records)
| line | category   | reason                                        |
|------|------------|-----------------------------------------------|
| L001 | assignment | 59-char shaped literal, b64, salt_alpha_a@v3  |
| L002 | assignment | 59-char shaped literal, b64, salt_alpha_a@v3  |
| L003 | decoy      | wrong shape label                             |
| L004 | decoy      | literal shape mismatch + wrong email pattern  |
| L005 | decoy      | literal shape mismatch (hex, len 4)           |
| L006 | malformed  | empty candidate                               |
| L007 | malformed  | missing line_id                               |

Counts: 2 assignments, 3 decoys, 2 malformed.

## Redaction guarantee
Reports contain only: line_id, category, SHA-256 digests, entropy (bits),
salt linkage string, encoded/salted booleans, validation drift list. Candidate
material is never written to any report, log, or digest input other than the
SHA-256 one-way function. Test `test_redacted_report_contains_no_candidate_material`
asserts no fixture candidate string appears in serialized output.

## Misuse-prevention matrix
| Risk                                   | Control                                                        |
|----------------------------------------|----------------------------------------------------------------|
| Live secret extraction                 | No network, no env reads, no filesystem globbing; explicit fixture path only (`_guard_fixture_path` rejects URLs/non-files) |
| Scanning real logs                     | Shape gate requires `SYNTHETIC_LOG_HOST_ALPHA_10` host + `SYNTHETIC_DB_PASSWORD_SHAPE` label; anything else is decoy/drift |
| Credential retention                   | Candidates never serialized; only digests/entropy/length emitted |
| Account enumeration                    | No auth attempts, no email validation beyond literal match to the designated `.invalid` pattern |
| Exfiltration                           | Output is in-memory dicts / stdout; no upload paths exist       |
| Target mutation / lateral movement     | Tool is pure read-only parsing; no write/exec primitives        |
| Re-identification via digests          | Unsalted+salted SHA-256 of synthetic filler only; fixture values are non-functional shaped literals |

## Verification
```
python3 -m py_compile miner.py auditor.py
python3 -m unittest discover tests -v
```

## Idempotent cleanup procedure
Safe to run any number of times; removes only generated artifacts:
```
rm -rf __pycache__ tests/__pycache__
git checkout -- fixtures/ 2>/dev/null || true   # restore fixture if edited
```
The tool itself writes nothing, so no state cleanup is needed beyond bytecode
caches. Deleting the whole `lab/credminer/` directory is also idempotent
(`rm -rf lab/credminer`) and leaves no residue elsewhere in the repo.
