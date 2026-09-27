"""Bounded copyright remediation / attributed-text clearance CLI.

Reads supplied JSON rights metadata plus referenced TXT notice files for the
three assigned snippet records, validates them, applies license policy, and
emits an audit trail with evidence (checksums and hashes only; snippet text
is never printed, transformed, or redistributed).

Usage:
  python3 utility.py run  --meta-dir fixtures/subset_valid \
      [--txt-dir DIR] --out out [--reference-date YYYY-MM-DD]
  python3 utility.py clean --out out

Idempotence: given the same inputs and --reference-date, reruns produce
byte-identical audit_trail.json and evidence.json (atomic overwrite).
Cleanup: `clean` removes exactly the two generated artifacts and exits 0
whether or not they exist, so it is safe to run repeatedly.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

import policy_engine as pe

AUDIT_FILE = "audit_trail.json"
EVIDENCE_FILE = "evidence.json"
GENERATED = (AUDIT_FILE, EVIDENCE_FILE)


def _load_record(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        record = json.load(fh)
    if not isinstance(record, dict):
        raise ValueError(f"{path}: metadata must be a JSON object")
    return record


def _atomic_write(path: Path, payload: dict) -> None:
    blob = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(blob)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def audit_entry(record: dict, record_path: Path, txt_dir: Path,
                reference_date: date) -> dict:
    notice_file = str(record.get("notice_file", ""))
    notice_bytes: bytes | None = None
    if notice_file:
        candidate = txt_dir / notice_file
        if candidate.is_file():
            notice_bytes = candidate.read_bytes()

    gaps = pe.validate_record(record, notice_bytes, reference_date)
    policy = pe.decide(str(record.get("license", "")))
    decision = policy["decision"]
    if gaps and decision == "cleared_with_attribution":
        decision = "held_pending_gaps"

    return {
        "name": record.get("snippet_id"),
        "title": record.get("title"),
        "filename": notice_file or None,
        "metadata_file": record_path.name,
        "license": record.get("license"),
        "author": record.get("author"),
        "rights_holder": record.get("rights_holder"),
        "assigned_date": record.get("assigned_date"),
        "rights_expiry": record.get("rights_expiry"),
        "record_checksum": pe.canonical_checksum(record),
        "notice_sha256": pe.text_hash(notice_bytes) if notice_bytes else None,
        "decision": decision,
        "policy": policy,
        "gaps": gaps,
    }


def run(meta_dir: Path, txt_dir: Path, out_dir: Path,
        reference_date: date) -> dict:
    records = sorted(meta_dir.glob("*.json"))
    if not records:
        raise SystemExit(f"no JSON metadata found in {meta_dir}")

    entries = [audit_entry(_load_record(p), p, txt_dir, reference_date)
               for p in records]
    entries.sort(key=lambda e: (str(e["name"]), str(e["metadata_file"])))

    audit = {
        "namespace": pe.NAMESPACE,
        "archive_path": pe.ARCHIVE_PATH,
        "external_archive_origin": pe.EXTERNAL_ARCHIVE_ORIGIN,
        "review_committee": pe.REVIEW_COMMITTEE,
        "publisher_contact": pe.PUBLISHER_CONTACT,
        "reference_date": reference_date.isoformat(),
        "entries": entries,
    }
    evidence = {
        "namespace": pe.NAMESPACE,
        "items": [
            {
                "name": e["name"],
                "filename": e["filename"],
                "license": e["license"],
                "rights_holder": e["rights_holder"],
                "record_checksum": e["record_checksum"],
                "decision": e["decision"],
                "notice_sha256": e["notice_sha256"],
                "gaps": e["gaps"],
            }
            for e in entries
        ],
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(out_dir / AUDIT_FILE, audit)
    _atomic_write(out_dir / EVIDENCE_FILE, evidence)

    for e in entries:
        print(f"{e['name']}: {e['decision']} gaps={e['gaps'] or 'none'}")
    return audit


def clean(out_dir: Path) -> None:
    for name in GENERATED:
        target = out_dir / name
        if target.exists():
            target.unlink()
            print(f"removed {target}")
        else:
            print(f"absent {target} (ok)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="validate records and emit audit trail")
    run_p.add_argument("--meta-dir", type=Path, required=True)
    run_p.add_argument("--txt-dir", type=Path, default=None,
                       help="defaults to --meta-dir")
    run_p.add_argument("--out", type=Path, required=True)
    run_p.add_argument("--reference-date", type=date.fromisoformat,
                       default=date.today())

    clean_p = sub.add_parser("clean", help="remove generated artifacts")
    clean_p.add_argument("--out", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "run":
        run(args.meta_dir, args.txt_dir or args.meta_dir, args.out,
            args.reference_date)
    else:
        clean(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
