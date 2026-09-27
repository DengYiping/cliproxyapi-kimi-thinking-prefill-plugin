"""Policy engine for the bounded attributed-text clearance utility.

Scope: exactly the three explicitly assigned snippet records. The engine
validates rights metadata and license policy; it never emits, transforms,
or reproduces snippet text. External archive origins, committees, and
publisher contacts remain placeholders by design.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date

NAMESPACE = "OPEN_SNIPPET_TITLES_CLEARANCE_TWO"  # placeholder content only
ARCHIVE_PATH = "LICENSE_ARCHIVE_ARCHIVE_FILES"

# External provenance placeholders (sanctioned; do not resolve).
EXTERNAL_ARCHIVE_ORIGIN = "PLACEHOLDER_EXTERNAL_ARCHIVE_ORIGIN"
REVIEW_COMMITTEE = "PLACEHOLDER_REVIEW_COMMITTEE"
PUBLISHER_CONTACT = "PLACEHOLDER_PUBLISHER_CONTACT"

# The three explicitly assigned records: id -> (license label, assigned date).
ASSIGNED_SNIPPETS = {
    "SNIPPET_A": ("MIT", "2018-11-02"),
    "SNIPPET_B": ("Apache-2.0", "2019-06-01"),
    "SNIPPET_C": ("all-rights-reserved", "2019-03-08"),
}

SUPPORTED_LICENSES = frozenset({"MIT", "Apache-2.0", "all-rights-reserved"})
ATTRIBUTION_LICENSES = frozenset({"MIT", "Apache-2.0"})

_NOTICE_RE = re.compile(
    r"(?i)(copyright|licen[cs]ed?\b|permission is hereby granted|all rights reserved)"
)

REQUIRED_FIELDS = ("snippet_id", "author", "rights_holder", "license",
                   "assigned_date", "rights_expiry", "notice_file")


def canonical_checksum(record: dict) -> str:
    """SHA-256 over the canonical JSON of the rights record."""
    blob = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def text_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_iso(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def decide(license_label: str) -> dict:
    """Policy decision for a validated license label."""
    if license_label in ATTRIBUTION_LICENSES:
        return {
            "decision": "cleared_with_attribution",
            "requires_attribution": True,
            "requires_notice_retention": True,
            "reviewer_request_only": False,
        }
    if license_label == "all-rights-reserved":
        return {
            "decision": "blocked_reviewer_request_only",
            "requires_attribution": True,
            "requires_notice_retention": True,
            "reviewer_request_only": True,
        }
    return {
        "decision": "rejected_unknown_license",
        "requires_attribution": False,
        "requires_notice_retention": False,
        "reviewer_request_only": False,
    }


def validate_record(record: dict, notice_bytes: bytes | None,
                    reference_date: date) -> list[str]:
    """Return the list of gap codes for a record. Empty list means clean."""
    gaps: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in record:
            gaps.append(f"missing_field:{field}")

    label = record.get("license")
    if label is not None and label not in SUPPORTED_LICENSES:
        gaps.append("unknown_license")

    if not str(record.get("author") or "").strip():
        gaps.append("missing_author")
    if not str(record.get("rights_holder") or "").strip():
        gaps.append("missing_rights_holder")

    assigned = _parse_iso(str(record.get("assigned_date", "")))
    expiry = _parse_iso(str(record.get("rights_expiry", "")))
    if assigned is None:
        gaps.append("invalid_assigned_date")
    if expiry is None:
        gaps.append("invalid_rights_expiry")
    if assigned and expiry:
        if expiry <= assigned:
            gaps.append("expiry_precedes_assignment")
        elif expiry < reference_date:
            gaps.append("rights_expired")

    snippet_id = record.get("snippet_id")
    if snippet_id in ASSIGNED_SNIPPETS and assigned is not None:
        expected_license, expected_date = ASSIGNED_SNIPPETS[snippet_id]
        if label == expected_license and assigned != _parse_iso(expected_date):
            gaps.append("assignment_date_mismatch")

    if notice_bytes is None:
        gaps.append("missing_notice_file")
    elif not _NOTICE_RE.search(notice_bytes.decode("utf-8", "replace")):
        gaps.append("missing_notice")

    return gaps
