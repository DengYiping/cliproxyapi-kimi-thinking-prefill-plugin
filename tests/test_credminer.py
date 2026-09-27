"""Unittests for the synthetic credential-shaped-string miner and salt auditor.

All fixtures are requester-supplied synthetic data. No live hosts, emails,
IPs, or real secrets appear anywhere in this suite.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from miner import (MineResult, emit_redacted, is_base64_shaped, is_hex_shaped,
                   mine_csv, mine_json, mine_records, sha256_hex,
                   shannon_entropy)
from auditor import audit_salts, report_to_dict

ROOT = Path(__file__).resolve().parent.parent
CSV_FIXTURE = ROOT / "fixtures" / "credlab" / "synthetic_log.csv"
JSON_FIXTURE = ROOT / "fixtures" / "credlab" / "synthetic_log.json"

EMAIL = "buyer.info.sim@synthetic.invalid"
SHAPED = "SIMULATED-ONLY-SHAPE-LITERAL-59-CHARS-aaaaaaaaaaaaaaaaaaaaa"
SALT_ID = "salt_alpha_a"
SALT_VALUE = "SALTALPHAa0123456789abcd"

with open(JSON_FIXTURE, encoding="utf-8") as fh:
    JSON_DOC = json.load(fh)
SALTS = JSON_DOC["salts"]
VALUE_BY_LINE = {r["line_id"]: r["value"] for r in JSON_DOC["records"]}


def mine_json_fresh() -> MineResult:
    return mine_json(JSON_FIXTURE, SALT_VALUE)


def audit_json_fresh():
    result = mine_json_fresh()
    return audit_salts(result.findings, JSON_DOC["records"], SALTS)


class TestMinerAssignments(unittest.TestCase):
    def test_exactly_two_assignments(self):
        findings = mine_json_fresh().findings
        assignments = [f for f in findings if f.category == "assignment"]
        self.assertEqual(len(assignments), 2)
        self.assertEqual({f.line_id for f in assignments}, {"L001", "L002"})

    def test_shaped_literal_assignment(self):
        f = next(x for x in mine_json_fresh().findings if x.line_id == "L001")
        self.assertTrue(f.shape_ok)
        self.assertEqual(f.shape_drift, "ok")
        self.assertEqual(f.value_len, 59)
        self.assertEqual(f.encoding, "plaintext")
        self.assertEqual(f.digest, sha256_hex(SHAPED))
        self.assertTrue(f.salted)
        self.assertEqual(f.salt_id, SALT_ID)
        self.assertEqual(f.salted_digest, sha256_hex(SALT_VALUE + SHAPED))

    def test_email_assignment_unsalted(self):
        f = next(x for x in mine_json_fresh().findings if x.line_id == "L002")
        self.assertTrue(f.shape_ok)
        self.assertEqual(f.digest, sha256_hex(EMAIL))
        self.assertFalse(f.salted)
        self.assertIsNone(f.salted_digest)

    def test_entropy_and_digests_present(self):
        for f in mine_json_fresh().findings:
            self.assertEqual(len(f.digest), 64)
            self.assertGreater(f.entropy, 0.0)
            self.assertAlmostEqual(
                f.entropy,
                round(shannon_entropy(VALUE_BY_LINE[f.line_id]), 4),
                places=4)


class TestMinerDecoys(unittest.TestCase):
    def test_exactly_three_decoys(self):
        findings = mine_json_fresh().findings
        decoys = [f for f in findings if f.category == "decoy"]
        self.assertEqual(len(decoys), 3)
        self.assertEqual({f.line_id for f in decoys}, {"L003", "L004", "L005"})

    def test_encoded_decoys_separated(self):
        findings = {f.line_id: f for f in mine_json_fresh().findings}
        self.assertEqual(findings["L003"].encoding, "base64")
        self.assertEqual(findings["L004"].encoding, "hex")
        self.assertEqual(findings["L005"].encoding, "plaintext")

    def test_shape_helpers(self):
        self.assertTrue(is_base64_shaped("U1lOVEhFVElDLURFQ09ZLUJBU0U2NC1QQVlMT0FE"))
        self.assertTrue(is_hex_shaped("deadbeef" * 8))
        self.assertFalse(is_base64_shaped("rotate-me-soon"))
        self.assertFalse(is_hex_shaped("rotate-me-soon"))


class TestMalformedRows(unittest.TestCase):
    def test_exactly_two_malformed_json(self):
        result = mine_json_fresh()
        self.assertEqual(len(result.malformed), 2)
        bad_ids = {m["line_id"] for m in result.malformed}
        self.assertEqual(bad_ids, {"L006", "L007"})

    def test_malformed_reasons(self):
        reasons = {m["line_id"]: m["reason"] for m in mine_json_fresh().malformed}
        self.assertIn("missing fields", reasons["L006"])
        self.assertIn("age_days", reasons["L006"])
        self.assertIn("not an integer", reasons["L007"])

    def test_csv_has_no_malformed_and_five_findings(self):
        result = mine_csv(CSV_FIXTURE, SALT_VALUE)
        self.assertEqual(len(result.malformed), 0)
        self.assertEqual(len(result.findings), 5)

    def test_missing_everything_is_malformed(self):
        result = mine_records([{"line_id": "X1"}], "inline", SALT_VALUE)
        self.assertEqual(len(result.malformed), 1)
        self.assertEqual(result.malformed[0]["line_id"], "X1")
        self.assertEqual(len(result.findings), 0)


class TestSaltAuditor(unittest.TestCase):
    def test_salt_linkage_and_length(self):
        report = audit_json_fresh()
        self.assertEqual(len(report.linkages), 1)
        link = report.linkages[0]
        self.assertEqual(link.salt_id, SALT_ID)
        self.assertEqual(link.salt_length, 24)
        self.assertTrue(link.length_ok)
        self.assertTrue(link.version_ok)

    def test_duplicate_salt_linkage_detected(self):
        report = audit_json_fresh()
        # L001 and L003 both reference salt_alpha_a.
        self.assertEqual(report.duplicate_salt_linkages, [SALT_ID])
        self.assertTrue(any("shared by 2 lines" in d for d in report.drift))

    def test_rollover_eligibility(self):
        report = audit_json_fresh()
        # L001: salted, age 120 >= 90. L003: salted but age 30 < 90.
        self.assertEqual(report.rollover_eligible, ["L001"])

    def test_rollover_boundary(self):
        records = [dict(r) for r in JSON_DOC["records"] if r["line_id"] == "L003"]
        records[0]["age_days"] = 90
        findings = mine_records(records, "inline", SALT_VALUE).findings
        report = audit_salts(findings, records, SALTS)
        self.assertEqual(report.rollover_eligible, ["L003"])

    def test_unsalted_assignment_flagged(self):
        report = audit_json_fresh()
        self.assertEqual(report.unsalted_assignments, ["L002"])

    def test_report_dict_keys(self):
        d = report_to_dict(audit_json_fresh())
        self.assertEqual(d["salt_version"], 3)
        self.assertEqual(d["salt_target_length"], 24)
        self.assertEqual(d["rotation_days"], 90)
        for key in ("linkages", "duplicate_salt_linkages", "rollover_eligible",
                    "unsalted_assignments", "drift"):
            self.assertIn(key, d)


class TestEmptyRedaction(unittest.TestCase):
    def test_redacted_rows_have_no_values(self):
        rows = emit_redacted(mine_json_fresh())
        self.assertEqual(len(rows), 5)
        forbidden = [SHAPED, EMAIL, "rotate-me-soon",
                     "U1lOVEhFVElDLURFQ09ZLUJBU0U2NC1QQVlMT0FE"]
        for row in rows:
            blob = json.dumps(row)
            for raw in forbidden:
                self.assertNotIn(raw, blob)
            self.assertNotIn("value", row)

    def test_empty_input_emits_empty_redaction(self):
        result = mine_records([], "inline", SALT_VALUE)
        self.assertEqual(emit_redacted(result), [])
        self.assertEqual(result.findings, [])
        self.assertEqual(result.malformed, [])

    def test_no_real_hosts_emails_or_ips(self):
        blob = json.dumps(emit_redacted(mine_json_fresh()))
        self.assertNotIn(".com", blob)
        self.assertNotIn("@", blob.replace("synthetic.invalid", ""))
        self.assertNotRegex(blob, r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")


if __name__ == "__main__":
    unittest.main()
