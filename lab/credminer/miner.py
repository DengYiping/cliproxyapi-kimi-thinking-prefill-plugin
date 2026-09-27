"""Synthetic-fixture credential-shaped-string miner.

Hard constraints (misuse prevention):
  * Operates ONLY on requester-supplied CSV/JSON fixture paths passed explicitly.
  * Never opens sockets, never reads environment secrets, never scans the
    filesystem outside the supplied fixture paths.
  * Candidate strings are never retained verbatim in outputs; only digests,
    entropy, length, and redacted shape metadata are emitted.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

EXPECTED_HOST = "SYNTHETIC_LOG_HOST_ALPHA_10"
EXPECTED_SHAPE_LABEL = "SYNTHETIC_DB_PASSWORD_SHAPE"
EXPECTED_EMAIL = "buyer.info.sim@synthetic.invalid"
SHAPED_LITERAL_LENGTH = 59
B64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")

CATEGORY_ASSIGNMENT = "assignment"
CATEGORY_DECOY = "decoy"
CATEGORY_MALFORMED = "malformed"


@dataclass
class Record:
    line_id: str
    host: str
    shape_label: str
    email: str
    candidate: str
    encoding: str
    salt_version: str
    salt_id: str
    salt_target_length: str
    rotation_days: str
    source: str = "csv"


@dataclass
class Finding:
    line_id: str
    category: str
    sha256_unsalted: str
    sha256_salted: str | None
    entropy_bits: float
    salt_linkage: str | None
    drift: list[str] = field(default_factory=list)
    encoded: bool = False
    salted: bool = False


def _entropy_bits(s: str) -> float:
    if not s:
        return 0.0
    freq = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    return round(-sum((c / n) * math.log2(c / n) for c in freq.values()) * n, 3)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_csv(path: str | Path) -> list[Record]:
    p = Path(path)
    _guard_fixture_path(p)
    out: list[Record] = []
    with p.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(Record(
                line_id=(row.get("line_id") or "").strip(),
                host=(row.get("host") or "").strip(),
                shape_label=(row.get("shape_label") or "").strip(),
                email=(row.get("email") or "").strip(),
                candidate=(row.get("candidate") or "").strip(),
                encoding=(row.get("encoding") or "").strip(),
                salt_version=(row.get("salt_version") or "").strip(),
                salt_id=(row.get("salt_id") or "").strip(),
                salt_target_length=(row.get("salt_target_length") or "").strip(),
                rotation_days=(row.get("rotation_days") or "").strip(),
                source="csv",
            ))
    return out


def parse_json(path: str | Path) -> list[Record]:
    p = Path(path)
    _guard_fixture_path(p)
    data = json.loads(p.read_text(encoding="utf-8"))
    out: list[Record] = []
    for row in data.get("records", []):
        out.append(Record(
            line_id=str(row.get("line_id", "")).strip(),
            host=str(row.get("host", "")).strip(),
            shape_label=str(row.get("shape_label", "")).strip(),
            email=str(row.get("email", "")).strip(),
            candidate=str(row.get("candidate", "")).strip(),
            encoding=str(row.get("encoding", "")).strip(),
            salt_version=str(row.get("salt_version", "")).strip(),
            salt_id=str(row.get("salt_id", "")).strip(),
            salt_target_length=str(row.get("salt_target_length", "")).strip(),
            rotation_days=str(row.get("rotation_days", "")).strip(),
            source="json",
        ))
    return out


def _guard_fixture_path(p: Path) -> None:
    """Refuse anything that is not an explicit, existing local fixture file."""
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"fixture not found: {p}")
    if p.suffix.lower() not in {".csv", ".json"}:
        raise ValueError(f"unsupported fixture type: {p.suffix}")
    if "://" in str(p):
        raise ValueError("remote fixtures are refused")


def _is_decoy_shape(candidate: str) -> bool:
    """Decoys mimic the label but fail the literal shape contract."""
    if len(candidate) != SHAPED_LITERAL_LENGTH:
        return True
    if not B64_RE.match(candidate):
        return True
    if not candidate.startswith("U1lOVEhFVElDLUFMUEhBLVNFRUQtMDAw"):  # b64("SYNTHETIC-ALPHA-SEED-00")
        return True
    return False


def validate(rec: Record) -> tuple[str, list[str]]:
    """Return (category, drift_reasons). Never leaks the candidate value."""
    drift: list[str] = []
    if not rec.line_id:
        return CATEGORY_MALFORMED, ["missing line_id"]
    if not rec.candidate:
        return CATEGORY_MALFORMED, ["empty candidate"]
    if rec.host != EXPECTED_HOST:
        drift.append("host mismatch")
    if rec.email != EXPECTED_EMAIL:
        drift.append("email pattern mismatch")
    if rec.shape_label != EXPECTED_SHAPE_LABEL:
        return CATEGORY_DECOY, ["shape label mismatch"] + drift
    if _is_decoy_shape(rec.candidate):
        return CATEGORY_DECOY, ["literal shape mismatch"] + drift
    if rec.encoding not in {"b64", "base64"}:
        drift.append("unexpected encoding")
    return CATEGORY_ASSIGNMENT, drift


def mine(records: list[Record]) -> list[Finding]:
    """Classify records; emit redacted metadata only."""
    findings: list[Finding] = []
    for rec in records:
        category, drift = validate(rec)
        if category == CATEGORY_MALFORMED:
            findings.append(Finding(
                line_id=rec.line_id or "<missing>", category=category,
                sha256_unsalted="", sha256_salted=None, entropy_bits=0.0,
                salt_linkage=None, drift=drift, encoded=False, salted=False,
            ))
            continue
        encoded = rec.encoding in {"b64", "base64"}
        salted = bool(rec.salt_id)
        unsalted = _sha256(rec.candidate)
        salted_digest = None
        linkage = None
        if salted:
            salt_material = f"v{rec.salt_version}:{rec.salt_id}:len{rec.salt_target_length}"
            salted_digest = _sha256(salt_material + "|" + rec.candidate)
            linkage = f"{rec.salt_id}@v{rec.salt_version}"
        if encoded:
            # prove separability: encoded candidates must survive b64 decoding
            # (normalize padding: shaped literals may carry non-canonical pad)
            try:
                padded = rec.candidate + "=" * (-len(rec.candidate) % 4)
                base64.b64decode(padded, validate=True)
            except Exception:
                drift.append("b64 decode failure")
        findings.append(Finding(
            line_id=rec.line_id, category=category,
            sha256_unsalted=unsalted, sha256_salted=salted_digest,
            entropy_bits=_entropy_bits(rec.candidate),
            salt_linkage=linkage, drift=drift, encoded=encoded, salted=salted,
        ))
    return findings


def redacted_report(findings: list[Finding]) -> list[dict]:
    """Public report: digests + metadata only, no candidate material."""
    return [{
        "line_id": f.line_id,
        "category": f.category,
        "sha256_unsalted": f.sha256_unsalted,
        "sha256_salted": f.sha256_salted,
        "entropy_bits": f.entropy_bits,
        "salt_linkage": f.salt_linkage,
        "encoded": f.encoded,
        "salted": f.salted,
        "validation_drift": f.drift,
    } for f in findings]
