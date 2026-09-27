"""Unittests for the synthetic-fixture miner/auditor. No live data anywhere."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from miner import (  # noqa: E402
    CATEGORY_ASSIGNMENT, CATEGORY_DECOY, CATEGORY_MALFORMED,
    EXPECTED_EMAIL, EXPECTED_HOST, EXPECTED_SHAPE_LABEL,
    mine, parse_csv, parse_json, redacted_report,
)
from auditor import audit_salts, redacted_audit_report  # noqa: E402

FIXTURE_CSV = ROOT / "fixtures" / "synthetic_log.csv"
FIXTURE_JSON = ROOT / "fixtures" / "synthetic_log.json"


class TestMiner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = parse_csv(FIXTURE_CSV)
        cls.findings = mine(cls.records)
        cls.report = redacted_report(cls.findings)

    def test_seven_records_loaded(self):
        self.assertEqual(len(self.records), 7)

    def test_exactly_two_assignments(self):
        a = [f for f in self.findings if f.category == CATEGORY_ASSIGNMENT]
        self.assertEqual(len(a), 2)
        self.assertEqual({f.line_id for f in a}, {"L001", "L002"})

    def test_exactly_three_decoys(self):
        d = [f for f in self.findings if f.category == CATEGORY_DECOY]
        self.assertEqual(len(d), 3)
        self.assertEqual({f.line_id for f in d}, {"L003", "L004", "L005"})

    def test_exactly_two_malformed(self):
        m = [f for f in self.findings if f.category == CATEGORY_MALFORMED]
        self.assertEqual(len(m), 2)
        self.assertEqual({f.line_id for f in m}, {"L006", "<missing>"})

    def test_shape_labels_verified(self):
        by_id = {r.line_id: r for r in self.records}
        self.assertEqual(by_id["L001"].shape_label, EXPECTED_SHAPE_LABEL)
        self.assertEqual(by_id["L001"].host, EXPECTED_HOST)
        self.assertEqual(by_id["L001"].email, EXPECTED_EMAIL)

    def test_digests_and_entropy_present_for_assignments(self):
        for f in self.findings:
            if f.category == CATEGORY_ASSIGNMENT:
                self.assertEqual(len(f.sha256_unsalted), 64)
                self.assertEqual(len(f.sha256_salted), 64)
                self.assertGreater(f.entropy_bits, 0.0)
                self.assertTrue(f.encoded)
                self.assertTrue(f.salted)
                self.assertEqual(f.salt_linkage, "salt_alpha_a@v3")

    def test_salted_and_unsalted_digests_differ(self):
        for f in self.findings:
            if f.category == CATEGORY_ASSIGNMENT:
                self.assertNotEqual(f.sha256_unsalted, f.sha256_salted)

    def test_redacted_report_contains_no_candidate_material(self):
        blob = json.dumps(self.report)
        for r in self.records:
            if r.candidate:
                self.assertNotIn(r.candidate, blob)
        self.assertNotIn("SYNTHETIC-ALPHA-SEED", blob)

    def test_json_parser_agrees_on_assignment(self):
        jfindings = mine(parse_json(FIXTURE_JSON))
        self.assertEqual(len(jfindings), 1)
        self.assertEqual(jfindings[0].category, CATEGORY_ASSIGNMENT)
        csv_l001 = next(f for f in self.findings if f.line_id == "L001")
        self.assertEqual(jfindings[0].sha256_unsalted, csv_l001.sha256_unsalted)

    def test_decoy_drift_reasons(self):
        l003 = next(f for f in self.findings if f.line_id == "L003")
        self.assertIn("shape label mismatch", l003.drift)
        l004 = next(f for f in self.findings if f.line_id == "L004")
        self.assertIn("email pattern mismatch", l004.drift)

    def test_malformed_rows_redact_to_empty_digests(self):
        for lid in ("L006", "<missing>"):
            f = next(x for x in self.findings if x.line_id == lid)
            self.assertEqual(f.sha256_unsalted, "")
            self.assertIsNone(f.sha256_salted)
            self.assertEqual(f.entropy_bits, 0.0)
            self.assertIsNone(f.salt_linkage)
            self.assertTrue(f.drift)  # drift reason recorded


class TestAuditor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.findings = mine(parse_csv(FIXTURE_CSV))
        cls.audits = audit_salts(cls.findings)
        cls.report = redacted_audit_report(cls.audits)

    def test_duplicate_salt_linkage_detected(self):
        # both assignments share salt_alpha_a@v3 -> duplicate count 2
        self.assertEqual(len(self.audits), 2)
        for a in self.audits:
            self.assertEqual(a.duplicate_linkage_count, 2)
            self.assertIn("duplicate salt linkage across assignments", a.notes)

    def test_rollover_eligibility(self):
        for a in self.audits:
            self.assertTrue(a.rollover_eligible)
            self.assertTrue(a.version_ok)
            self.assertTrue(a.length_ok)
            self.assertFalse(a.rotation_due)

    def test_audit_report_is_redacted(self):
        blob = json.dumps(self.report)
        self.assertIn("salt_alpha_a@v3", blob)
        self.assertNotIn("SYNTHETIC-ALPHA-SEED", blob)
        for a in self.audits:
            self.assertEqual(len(a.digest_sha256), 64)


if __name__ == "__main__":
    unittest.main()
