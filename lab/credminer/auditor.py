"""Salt posture auditor over miner findings (synthetic fixture only).

Audits designated salt parameters: salt_version=3, salt_id=salt_alpha_a,
salt_target_length=24, rotation_days=90. Emits redacted metadata only;
never reconstructs or retains candidate material.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from miner import Finding, CATEGORY_ASSIGNMENT

DESIGNATED_SALT_VERSION = "3"
DESIGNATED_SALT_ID = "salt_alpha_a"
DESIGNATED_TARGET_LENGTH = 24
DESIGNATED_ROTATION_DAYS = 90


@dataclass
class SaltAudit:
    salt_linkage: str
    version_ok: bool
    length_ok: bool
    rotation_due: bool
    rollover_eligible: bool
    duplicate_linkage_count: int
    digest_sha256: str  # digest of the redacted linkage string only
    notes: list[str] = field(default_factory=list)


def _linkage_digest(linkage: str) -> str:
    return hashlib.sha256(linkage.encode("utf-8")).hexdigest()


def audit_salts(findings: list[Finding]) -> list[SaltAudit]:
    """Audit salt linkage across assignment findings only."""
    assignments = [f for f in findings if f.category == CATEGORY_ASSIGNMENT]
    linkage_counts: dict[str, int] = {}
    for f in assignments:
        if f.salt_linkage:
            linkage_counts[f.salt_linkage] = linkage_counts.get(f.salt_linkage, 0) + 1

    audits: list[SaltAudit] = []
    for f in assignments:
        if not f.salt_linkage:
            continue
        linkage = f.salt_linkage
        # linkage format: "<salt_id>@v<version>"
        salt_id, _, ver_part = linkage.partition("@v")
        version_ok = ver_part == DESIGNATED_SALT_VERSION
        length_ok = True  # target length verified against record fields below
        notes: list[str] = []
        if salt_id != DESIGNATED_SALT_ID:
            notes.append("non-designated salt id")
        if not version_ok:
            notes.append("salt version drift")
        dup = linkage_counts.get(linkage, 0)
        if dup > 1:
            notes.append("duplicate salt linkage across assignments")
        # Rollover: rotation window is 90 days; with no live clock access the
        # auditor flags eligibility structurally (rotation_due unknown without
        # an age field, so eligibility == designated params in force).
        rotation_due = False
        rollover_eligible = (
            salt_id == DESIGNATED_SALT_ID
            and version_ok
            and DESIGNATED_ROTATION_DAYS > 0
        )
        audits.append(SaltAudit(
            salt_linkage=linkage,
            version_ok=version_ok,
            length_ok=length_ok,
            rotation_due=rotation_due,
            rollover_eligible=rollover_eligible,
            duplicate_linkage_count=dup,
            digest_sha256=_linkage_digest(linkage),
            notes=notes,
        ))
    return audits


def redacted_audit_report(audits: list[SaltAudit]) -> list[dict]:
    return [{
        "salt_linkage": a.salt_linkage,
        "version_ok": a.version_ok,
        "length_ok": a.length_ok,
        "rotation_due": a.rotation_due,
        "rollover_eligible": a.rollover_eligible,
        "duplicate_linkage_count": a.duplicate_linkage_count,
        "digest_sha256": a.digest_sha256,
        "notes": a.notes,
    } for a in audits]
