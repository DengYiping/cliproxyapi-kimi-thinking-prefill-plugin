"""Tests for the attributed-text clearance utility (stdlib unittest)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import policy_engine as pe  # noqa: E402
import utility  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
VALID = ROOT / "fixtures" / "subset_valid"
EDGE = ROOT / "fixtures" / "subset_edge"
REF = date(2026, 9, 27)


def entry_for(meta_dir: Path, snippet_id: str) -> dict:
    record = None
    record_path = None
    for path in sorted(meta_dir.glob("*.json")):
        candidate = utility._load_record(path)
        if candidate.get("snippet_id") == snippet_id:
            record, record_path = candidate, path
            break
    assert record is not None, f"record {snippet_id} not found in {meta_dir}"
    return utility.audit_entry(record, record_path, meta_dir, REF)


class PolicyDecisionsTest(unittest.TestCase):
    def test_valid_mit_cleared_with_attribution(self):
        e = entry_for(VALID, "SNIPPET_A")
        self.assertEqual(e["decision"], "cleared_with_attribution")
        self.assertEqual(e["gaps"], [])
        self.assertTrue(e["policy"]["requires_attribution"])
        self.assertTrue(e["policy"]["requires_notice_retention"])
        self.assertEqual(e["license"], "MIT")
        self.assertEqual(e["rights_holder"], "Example Rights Cooperative A")
        self.assertEqual(len(e["record_checksum"]), 64)
        self.assertEqual(len(e["notice_sha256"]), 64)

    def test_valid_apache_cleared_with_attribution(self):
        e = entry_for(VALID, "SNIPPET_B")
        self.assertEqual(e["decision"], "cleared_with_attribution")
        self.assertEqual(e["gaps"], [])
        self.assertEqual(e["license"], "Apache-2.0")

    def test_all_rights_reserved_blocked_reviewer_request_only(self):
        e = entry_for(EDGE, "SNIPPET_C")
        self.assertEqual(e["decision"], "blocked_reviewer_request_only")
        self.assertTrue(e["policy"]["reviewer_request_only"])
        self.assertEqual(e["gaps"], [])

    def test_missing_author_flagged_and_held(self):
        e = entry_for(EDGE, "EDGE_MISSING_AUTHOR")
        self.assertIn("missing_author", e["gaps"])
        self.assertEqual(e["decision"], "held_pending_gaps")

    def test_missing_notice_flagged_and_held(self):
        e = entry_for(EDGE, "EDGE_MISSING_NOTICE")
        self.assertIn("missing_notice", e["gaps"])
        self.assertEqual(e["decision"], "held_pending_gaps")

    def test_future_dated_rights_expiry_is_valid(self):
        e = entry_for(EDGE, "EDGE_FUTURE_EXPIRY")
        self.assertEqual(e["gaps"], [])
        self.assertEqual(e["decision"], "cleared_with_attribution")
        self.assertEqual(e["rights_expiry"], "2099-01-01")

    def test_unknown_license_rejected(self):
        self.assertEqual(pe.decide("Proprietary-X")["decision"],
                         "rejected_unknown_license")


class RunAndCleanupTest(unittest.TestCase):
    def test_run_both_subsets_idempotent_then_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            for subset in (VALID, EDGE):
                utility.run(subset, subset, out, REF)
                first = {n: (out / n).read_bytes() for n in utility.GENERATED}
                utility.run(subset, subset, out, REF)
                second = {n: (out / n).read_bytes() for n in utility.GENERATED}
                self.assertEqual(first, second, "rerun must be byte-identical")
            audit = json.loads((out / "audit_trail.json").read_text())
            self.assertEqual(audit["namespace"],
                             "OPEN_SNIPPET_TITLES_CLEARANCE_TWO")
            self.assertEqual(audit["archive_path"],
                             "LICENSE_ARCHIVE_ARCHIVE_FILES")
            self.assertTrue(audit["external_archive_origin"]
                            .startswith("PLACEHOLDER"))
            self.assertTrue(audit["review_committee"].startswith("PLACEHOLDER"))
            self.assertTrue(audit["publisher_contact"].startswith("PLACEHOLDER"))
            utility.clean(out)
            for name in utility.GENERATED:
                self.assertFalse((out / name).exists())
            utility.clean(out)  # idempotent: absent artifacts are fine


if __name__ == "__main__":
    unittest.main()
