"""Synthetic credential-shaped-string miner.

Parses ONLY requester-supplied synthetic CSV/JSON fixtures. Never touches live
infrastructure, never emits raw candidate values; output is redacted metadata
(digests, entropy, shape labels) only.
"""
from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

ALLOWED_HOSTS = frozenset({"SYNTHETIC_LOG_HOST_ALPHA_10"})
EMAIL_PATTERN = "buyer.info.sim@synthetic.invalid"
FORBIDDEN_TOKENS = (
    "hubspot", ".com", ".net", ".org", ".io", "gmail", "prod", "production",
)
_IPV4_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_B64_RE = re.compile(r"^[A-Za-z0-9+/]{16,}={0,2}$")
_HEX_RE = re.compile(r"^[0-9a-fA-F]{32,}$")

REQUIRED_FIELDS = ("line_id", "kind", "host", "field", "value", "salt_id", "age_days")


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts: dict[str, int] = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(text)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def is_base64_shaped(value: str) -> bool:
    if not _B64_RE.match(value):
        return False
    try:
        base64.b64decode(value, validate=True)
        return True
    except binascii.Error:
        return False


def is_hex_shaped(value: str) -> bool:
    return bool(_HEX_RE.match(value))


@dataclass
class Finding:
    line_id: str
    category: str  # assignment | decoy
    encoding: str  # plaintext | base64 | hex
    digest: str
    entropy: float
    salted: bool
    salt_id: str | None
    salted_digest: str | None
    shape_ok: bool
    shape_drift: str
    value_len: int


@dataclass
class MineResult:
    findings: list[Finding] = field(default_factory=list)
    malformed: list[dict] = field(default_factory=list)
    host_rejections: list[str] = field(default_factory=list)


def _classify_shape(expected_label: str, value: str) -> tuple[bool, str]:
    """Verify the declared shape label against the observed value shape."""
    if expected_label == "SHAPED_LITERAL_59_CHARS":
        ok = len(value) == 59
        return ok, "ok" if ok else f"len={len(value)} != 59"
    if expected_label == "EMAIL_SIM":
        ok = value == EMAIL_PATTERN
        return ok, "ok" if ok else "value != designated synthetic email"
    if expected_label == "SHORT_LITERAL":
        # Decoy/opaque-blob label. The declared label is authoritative for the
        # label check; any encoding/length mismatch is still surfaced as
        # validation drift on the finding.
        return True, "ok"
    return False, f"unknown shape label {expected_label!r}"


def _looks_synthetic(host: str, value: str) -> tuple[bool, str]:
    if host not in ALLOWED_HOSTS:
        return False, f"host {host!r} not in synthetic allowlist"
    if _IPV4_RE.search(value) or _IPV4_RE.search(host):
        return False, "ipv4-literal rejected"
    low = value.lower()
    for tok in FORBIDDEN_TOKENS:
        if tok in low:
            return False, f"forbidden token {tok!r} in value"
    return True, "ok"


def _validate_record(rec: dict, source: str) -> tuple[dict | None, dict | None]:
    missing = [k for k in REQUIRED_FIELDS if k not in rec]
    if missing:
        return None, {"source": source, "line_id": rec.get("line_id", "?"),
                      "reason": f"missing fields: {','.join(missing)}"}
    if rec["kind"] not in ("assignment", "decoy"):
        return None, {"source": source, "line_id": rec["line_id"],
                      "reason": f"unknown kind {rec['kind']!r}"}
    try:
        rec["age_days"] = int(rec["age_days"])
    except (TypeError, ValueError):
        return None, {"source": source, "line_id": rec["line_id"],
                      "reason": "age_days not an integer"}
    return rec, None


def mine_records(records: list[dict], source: str, salt: str,
                 result: MineResult | None = None) -> MineResult:
    result = result or MineResult()
    for raw in records:
        rec, malformed = _validate_record(raw, source)
        if malformed:
            result.malformed.append(malformed)
            continue
        assert rec is not None
        ok, reason = _looks_synthetic(rec["host"], rec["value"])
        if not ok:
            result.host_rejections.append(f"{rec['line_id']}: {reason}")
            continue
        value = rec["value"]
        shape_ok, drift = _classify_shape(rec.get("shape_label", ""), value)
        salted = bool(rec.get("salt_id"))
        # Hex is checked first: a pure-hex string also matches the base64
        # alphabet, so the more specific classification must win.
        if is_hex_shaped(value):
            encoding = "hex"
        elif is_base64_shaped(value):
            encoding = "base64"
        else:
            encoding = "plaintext"
        # Surface shape/label/encoding drift even when the label itself is valid.
        if shape_ok:
            if encoding != "plaintext" and rec.get("shape_label") == "SHORT_LITERAL":
                drift = f"label=SHORT_LITERAL but value is {encoding}-shaped len={len(value)}"
            elif rec.get("shape_label") == "SHAPED_LITERAL_59_CHARS" and encoding != "plaintext":
                drift = f"literal label but value is {encoding}-shaped"
        result.findings.append(Finding(
            line_id=rec["line_id"],
            category=rec["kind"],
            encoding=encoding,
            digest=sha256_hex(value),
            entropy=round(shannon_entropy(value), 4),
            salted=salted,
            salt_id=rec.get("salt_id") or None,
            salted_digest=sha256_hex(salt + value) if salted else None,
            shape_ok=shape_ok,
            shape_drift=drift,
            value_len=len(value),
        ))
    return result


def mine_csv(path: str | Path, salt: str) -> MineResult:
    with open(path, newline="", encoding="utf-8") as fh:
        records = list(csv.DictReader(fh))
    return mine_records(records, str(path), salt)


def mine_json(path: str | Path, salt: str) -> MineResult:
    with open(path, encoding="utf-8") as fh:
        records = json.load(fh)["records"]
    return mine_records(records, str(path), salt)


def emit_redacted(result: MineResult) -> list[dict]:
    """Redacted evidence rows: no raw values, digests and metadata only."""
    return [{
        "line_id": f.line_id,
        "category": f.category,
        "encoding": f.encoding,
        "sha256": f.digest,
        "entropy": f.entropy,
        "salted": f.salted,
        "salt_id": f.salt_id,
        "salted_sha256": f.salted_digest,
        "shape_ok": f.shape_ok,
        "shape_drift": f.shape_drift,
        "value_len": f.value_len,
    } for f in result.findings]
