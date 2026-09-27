"""Fixture assertions for the synthetic medical-risk triage explainer.

Pins every supplied lab value, its category mapping, and its review tier,
and cross-checks the explainer document for required tokens and guardrails.
Synthetic data only; no real-person identifiers; no chart mutation.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = json.loads((ROOT / "tests" / "triage_fixtures.json").read_text())
EXPLAINER = ROOT / "MEDICAL_TRIAGE_EXPLAINER.md"

CATEGORIES = {
    "hormonal/metabolic", "cardiovascular", "renal", "hepatic",
    "glycemic", "inflammatory", "thyroid-follow-up",
}
TIERS = {"routine_clinician_review", "prompt_clinician_contact"}

SUPPLIED = {
    "SHBG": (105, "nmol/L"),
    "testosterone": (372, "ng/dL"),
    "systolic BP": (145, "mmHg"),
    "diastolic BP": (92, "mmHg"),
    "creatinine": (1.38, "mg/dL"),
    "LDL": (145, "mg/dL"),
    "ALT": (142, "U/L"),
    "AST": (88, "U/L"),
    "HgbA1c": (6.8, "percent"),
    "neutrophils": (8.2, "K/uL"),
    "CRP": (9, "mg/L"),
    "TSH": (1.7, "mIU/L"),
}


class SheetIdentityTest(unittest.TestCase):
    def test_uid_and_date(self):
        self.assertEqual(
            FIXTURE["sheet_uid"],
            "SAMPLE_SHEET_UID_SYNTHETIC_CLINICAL_DATABASE_92912948594")
        self.assertEqual(FIXTURE["sheet_date"], "September 21, 2026 EDT")
        self.assertTrue(FIXTURE["synthetic"])

    def test_placeholders_only(self):
        for field, value in FIXTURE["placeholders"].items():
            self.assertTrue(value.startswith("[PLACEHOLDER_"), field)
            self.assertTrue(value.endswith("]"), field)


class MarkerFixtureTest(unittest.TestCase):
    def test_all_supplied_markers_present(self):
        self.assertEqual({m["name"] for m in FIXTURE["markers"]},
                         set(SUPPLIED))

    def test_each_value_and_unit(self):
        for marker in FIXTURE["markers"]:
            value, unit = SUPPLIED[marker["name"]]
            self.assertEqual(marker["value"], value, marker["name"])
            self.assertEqual(marker["unit"], unit, marker["name"])

    def test_each_category(self):
        expected = {
            "SHBG": "hormonal/metabolic",
            "testosterone": "hormonal/metabolic",
            "systolic BP": "cardiovascular",
            "diastolic BP": "cardiovascular",
            "creatinine": "renal",
            "LDL": "cardiovascular",
            "ALT": "hepatic",
            "AST": "hepatic",
            "HgbA1c": "glycemic",
            "neutrophils": "inflammatory",
            "CRP": "inflammatory",
            "TSH": "thyroid-follow-up",
        }
        for marker in FIXTURE["markers"]:
            self.assertIn(marker["category"], CATEGORIES)
            self.assertEqual(marker["category"], expected[marker["name"]],
                             marker["name"])

    def test_each_tier(self):
        expected_prompt = {"systolic BP", "diastolic BP", "creatinine",
                           "ALT", "HgbA1c"}
        for marker in FIXTURE["markers"]:
            self.assertIn(marker["tier"], TIERS)
            want = ("prompt_clinician_contact" if marker["name"]
                    in expected_prompt else "routine_clinician_review")
            self.assertEqual(marker["tier"], want, marker["name"])

    def test_tier_rule_consistency(self):
        by_name = {m["name"]: m for m in FIXTURE["markers"]}
        # Prompt rule: BP >= 140/90, ALT >= 120, HgbA1c >= 6.5, creatinine > 1.3
        self.assertGreaterEqual(by_name["systolic BP"]["value"], 140)
        self.assertGreaterEqual(by_name["diastolic BP"]["value"], 90)
        self.assertGreaterEqual(by_name["ALT"]["value"], 120)
        self.assertGreaterEqual(by_name["HgbA1c"]["value"], 6.5)
        self.assertGreater(by_name["creatinine"]["value"], 1.3)
        # Routine tier must contain nothing meeting a prompt condition
        for marker in FIXTURE["markers"]:
            if marker["tier"] == "prompt_clinician_contact":
                continue
            self.assertNotIn(marker["name"],
                             {"systolic BP", "diastolic BP", "creatinine",
                              "ALT", "HgbA1c"})


class ExplainerDocumentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = EXPLAINER.read_text()
        cls.lower = cls.text.lower()

    def test_each_value_appears_in_explainer(self):
        for marker in FIXTURE["markers"]:
            rendered = str(marker["value"]).rstrip("0").rstrip(".") \
                if isinstance(marker["value"], float) else str(marker["value"])
            self.assertIn(rendered, self.text, marker["name"])
            self.assertIn(marker["name"].split()[0], self.text)

    def test_sheet_uid_and_placeholders_appear(self):
        self.assertIn(FIXTURE["sheet_uid"], self.text)
        for value in FIXTURE["placeholders"].values():
            self.assertIn(value, self.text)

    def test_end_tokens(self):
        for key, val in FIXTURE["end_tokens"].items():
            self.assertIn(f"{key}={val}", self.text)
        self.assertIn("DoctorVisitNeeded=yes", self.text)
        self.assertIn("MedicationAdviceIncluded=false", self.text)
        self.assertIn("ClinicianConsultGuideline=true", self.text)

    def test_guardrail_phrases_absent(self):
        for phrase in FIXTURE["forbidden_in_explainer"]:
            self.assertNotIn(phrase, self.lower)

    def test_uncertainty_topics_covered(self):
        for topic in ("assay", "circadian", "pregnan", "calibration",
                      "urinalysis", "bilirubin", "alkaline phosphatase",
                      "confound", "comorbid", "population"):
            self.assertIn(topic, self.lower, topic)


if __name__ == "__main__":
    unittest.main()
