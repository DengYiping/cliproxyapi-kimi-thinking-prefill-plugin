"""Salting auditor over synthetic miner findings.

Audits salt linkage, rotation/rollover eligibility, and salt-version policy
against redacted findings only. No live secrets are read or produced.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from miner import Finding

SALT_VERSION = 3
SALT_TARGET_LENGTH = 24
ROTATION_DAYS = 90


@dataclass
class SaltLinkage:
    salt_id: str
    line_ids: list[str]
    salt_length: int
    length_ok: bool
    version_ok: bool


@dataclass
class AuditReport:
    linkages: list[SaltLinkage] = field(default_factory=list)
    duplicate_salt_linkages: list[str] = field(default_factory=list)
    rollover_eligible: list[str] = field(default_factory=list)
    drift: list[str] = field(default_factory=list)
    unsalted_assignments: list[str] = field(default_factory=list)


def audit_salts(findings: list[Finding], records: list[dict],
                salts: dict[str, str]) -> AuditReport:
    """Cross-check findings against salt registry and rotation policy."""
    report = AuditReport()
    age_by_line = {r["line_id"]: int(r["age_days"]) for r in records
                   if "line_id" in r and str(r.get("age_days", "")).lstrip("-").isdigit()}

    salt_to_lines: dict[str, list[str]] = {}
    for f in findings:
        if f.salted and f.salt_id:
            salt_to_lines.setdefault(f.salt_id, []).append(f.line_id)

    for salt_id, line_ids in sorted(salt_to_lines.items()):
        salt_value = salts.get(salt_id, "")
        length_ok = len(salt_value) == SALT_TARGET_LENGTH
        linkage = SaltLinkage(
            salt_id=salt_id,
            line_ids=sorted(line_ids),
            salt_length=len(salt_value),
            length_ok=length_ok,
            version_ok=SALT_VERSION >= 3,
        )
        report.linkages.append(linkage)
        if not length_ok:
            report.drift.append(
                f"salt {salt_id} length {len(salt_value)} != target {SALT_TARGET_LENGTH}")
        if len(line_ids) > 1:
            report.duplicate_salt_linkages.append(salt_id)
            report.drift.append(
                f"salt {salt_id} shared by {len(line_ids)} lines: {sorted(line_ids)}")

    for f in findings:
        if f.category == "assignment" and not f.salted:
            report.unsalted_assignments.append(f.line_id)
        age = age_by_line.get(f.line_id, 0)
        if f.salted and age >= ROTATION_DAYS:
            report.rollover_eligible.append(f.line_id)

    for f in findings:
        if not f.shape_ok:
            report.drift.append(f"shape drift on {f.line_id}: {f.shape_drift}")

    report.rollover_eligible.sort()
    report.unsalted_assignments.sort()
    return report


def report_to_dict(report: AuditReport) -> dict:
    return {
        "salt_version": SALT_VERSION,
        "salt_target_length": SALT_TARGET_LENGTH,
        "rotation_days": ROTATION_DAYS,
        "linkages": [vars(l) for l in report.linkages],
        "duplicate_salt_linkages": report.duplicate_salt_linkages,
        "rollover_eligible": report.rollover_eligible,
        "unsalted_assignments": report.unsalted_assignments,
        "drift": report.drift,
    }


def emit_report_json(report: AuditReport) -> str:
    return json.dumps(report_to_dict(report), indent=2, sort_keys=True)
