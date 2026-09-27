#!/usr/bin/env python3
"""Lab-rooted DRM/license metadata extractor and destination migrator.

Metadata-only: reads rights profiles and content bytes of explicitly assigned
lab artifacts, validates detached HMAC tokens, and atomically migrates content
between lab destinations. No DRM scheme is implemented or circumvented; all
assets are placeholders under ./lab.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import uuid
from datetime import datetime, timezone

LAB_ROOT = os.environ.get("LAB_ROOT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "lab"))
LAB_TOKEN_KEY = b"lab-only-placeholder-token-key"  # lab fixture key, not a real secret

# Explicitly assigned artifacts. Anything not listed here is rejected.
ASSIGNED_ARTIFACTS = {
    "audio_lp_track_a": {
        "asset_id": "asset-audio-lp-track-a",
        "owner": "lab-owner-7",
        "destination_id": "dest-audio-vault",
        "rights_profile": {
            "license": "LAB-AUDIO-LP-1.0",
            "not_before": "2026-01-01T00:00:00Z",
            "not_after": "2027-01-01T00:00:00Z",
            "allowed_operations": ["extract-metadata", "migrate"],
            "attribution": "Lab Artist (placeholder)",
        },
    },
    "ebook_limited_reader_b": {
        "asset_id": "asset-ebook-limited-reader-b",
        "owner": "lab-owner-7",
        "destination_id": "dest-ebook-archive",
        "rights_profile": {
            "license": "LAB-LIMITED-READER-1.0",
            "not_before": "2026-01-01T00:00:00Z",
            "not_after": "2027-06-01T00:00:00Z",
            "allowed_operations": ["extract-metadata", "migrate"],
            "attribution": "Lab Author (placeholder)",
        },
    },
}

EXIT_CODES = {
    "UNASSIGNED_ARTIFACT": 2,
    "MISSING_SOURCE": 3,
    "MISSING_DESTINATION": 4,
    "OWNER_MISMATCH": 5,
    "EXPIRED_RIGHTS": 6,
    "RIGHTS_NOT_ACTIVE": 7,
    "TOKEN_INVALID": 8,
    "TOKEN_EXPIRED": 9,
    "DUPLICATE_KEY": 10,
}


class Fail(Exception):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def parse_rfc3339(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def rights_hash(profile):
    return hashlib.sha256(canon(profile).encode()).hexdigest()


def paths(name):
    a = ASSIGNED_ARTIFACTS[name]
    return {
        "source": os.path.join(LAB_ROOT, "source", name + ".bin"),
        "source_owner": os.path.join(LAB_ROOT, "source", name + ".owner"),
        "dest_dir": os.path.join(LAB_ROOT, "dest", a["destination_id"]),
        "dest_owner": os.path.join(LAB_ROOT, "dest", a["destination_id"], ".owner"),
        "ledger": os.path.join(LAB_ROOT, "state", "idempotency.json"),
    }


def assigned(name):
    if name not in ASSIGNED_ARTIFACTS:
        raise Fail("UNASSIGNED_ARTIFACT", "artifact %r is not explicitly assigned" % name)
    return ASSIGNED_ARTIFACTS[name]


def read_owner(path, code):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        raise Fail(code, "owner sidecar missing: %s" % path)


def preflight(name):
    """Per-item source/destination existence plus same-owner checks."""
    a = assigned(name)
    p = paths(name)
    if not os.path.isfile(p["source"]):
        raise Fail("MISSING_SOURCE", "source not found: %s" % p["source"])
    if not os.path.isdir(p["dest_dir"]):
        raise Fail("MISSING_DESTINATION", "destination not found: %s" % p["dest_dir"])
    src_owner = read_owner(p["source_owner"], "MISSING_SOURCE")
    dst_owner = read_owner(p["dest_owner"], "MISSING_DESTINATION")
    if src_owner != a["owner"] or dst_owner != a["owner"] or src_owner != dst_owner:
        raise Fail("OWNER_MISMATCH",
                   "expected owner %r, source=%r destination=%r" % (a["owner"], src_owner, dst_owner))
    return a, p


def check_rights_window(a, now):
    rp = a["rights_profile"]
    if now < parse_rfc3339(rp["not_before"]):
        raise Fail("RIGHTS_NOT_ACTIVE", "rights not active until %s" % rp["not_before"])
    if now > parse_rfc3339(rp["not_after"]):
        raise Fail("EXPIRED_RIGHTS", "rights expired at %s" % rp["not_after"])


def b64e(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def mint_token(asset_id, not_after):
    payload = canon({"asset_id": asset_id, "not_after": not_after, "scope": "migrate"}).encode()
    sig = hmac.new(LAB_TOKEN_KEY, payload, hashlib.sha256).digest()
    return b64e(payload) + "." + b64e(sig)


def validate_token(name, token_path, now):
    try:
        raw = open(token_path, "r", encoding="utf-8").read().strip()
        payload_b64, sig_b64 = raw.split(".")
        payload = b64d(payload_b64)
    except (OSError, ValueError):
        raise Fail("TOKEN_INVALID", "malformed detached token")
    expected = hmac.new(LAB_TOKEN_KEY, payload, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, b64d(sig_b64)):
        raise Fail("TOKEN_INVALID", "detached token signature mismatch")
    data = json.loads(payload.decode())
    if data.get("asset_id") != ASSIGNED_ARTIFACTS[name]["asset_id"]:
        raise Fail("TOKEN_INVALID", "token asset_id mismatch")
    if now > parse_rfc3339(data["not_after"]):
        raise Fail("TOKEN_EXPIRED", "token expired at %s" % data["not_after"])
    return data


def extract(name, now):
    a, p = preflight(name)
    check_rights_window(a, now)
    h = hashlib.sha256()
    size = 0
    with open(p["source"], "rb") as f:  # readonly: no writes to source
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
            size += len(chunk)
    return {
        "artifact": name,
        "asset_id": a["asset_id"],
        "destination_id": a["destination_id"],
        "content_sha256": h.hexdigest(),
        "content_bytes": size,
        "rights_profile": a["rights_profile"],
        "rights_hash": rights_hash(a["rights_profile"]),
        "extracted_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": "readonly",
    }


def load_ledger(path):
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def migrate(name, token_path, idem_key, now):
    a, p = preflight(name)
    check_rights_window(a, now)
    validate_token(name, token_path, now)
    ledger = load_ledger(p["ledger"])
    if idem_key in ledger:
        raise Fail("DUPLICATE_KEY", "idempotency key %r already used by receipt %s"
                   % (idem_key, ledger[idem_key]["receipt_id"]))
    meta = extract(name, now)
    receipt_id = "rcpt-" + uuid.uuid5(uuid.NAMESPACE_URL,
                                      "lab-migrate:" + a["asset_id"] + ":" + idem_key).hex[:16]
    dest_file = os.path.join(p["dest_dir"], name + ".bin")
    tmp_file = dest_file + ".tmp." + receipt_id
    with open(p["source"], "rb") as src, open(tmp_file, "wb") as dst:
        dst.write(src.read())
        dst.flush()
        os.fsync(dst.fileno())
    os.replace(tmp_file, dest_file)  # atomic within the destination directory
    receipt = {
        "receipt_id": receipt_id,
        "artifact": name,
        "asset_id": a["asset_id"],
        "destination_id": a["destination_id"],
        "idempotency_key": idem_key,
        "rights_hash": meta["rights_hash"],
        "content_sha256": meta["content_sha256"],
        "migrated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    ledger[idem_key] = receipt
    tmp_ledger = p["ledger"] + ".tmp"
    with open(tmp_ledger, "w", encoding="utf-8") as f:
        f.write(canon(ledger) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_ledger, p["ledger"])
    return receipt


def emit(obj):
    print(json.dumps(obj, indent=2, sort_keys=True))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lab DRM/license metadata extractor and migrator")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("extract", "validate-token", "migrate"):
        sp = sub.add_parser(c)
        sp.add_argument("artifact")
        sp.add_argument("--now", required=True, help="RFC3339 evaluation time (deterministic)")
        if c in ("validate-token", "migrate"):
            sp.add_argument("--token", required=True)
        if c == "migrate":
            sp.add_argument("--idempotency-key", required=True)
    mt = sub.add_parser("mint-token", help="lab-only fixture generator")
    mt.add_argument("artifact")
    mt.add_argument("--not-after", required=True)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "mint-token":
            a = assigned(args.artifact)
            print(mint_token(a["asset_id"], args.not_after))
            return 0
        now = parse_rfc3339(args.now)
        if args.cmd == "extract":
            emit(extract(args.artifact, now))
        elif args.cmd == "validate-token":
            preflight(args.artifact)
            emit({"token": validate_token(args.artifact, args.token, now), "valid": True})
        else:
            emit(migrate(args.artifact, args.token, args.idempotency_key, now))
        return 0
    except Fail as e:
        print(canon({"error": e.code, "detail": e.detail}))
        return EXIT_CODES[e.code]


if __name__ == "__main__":
    sys.exit(main())
