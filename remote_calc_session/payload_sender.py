#!/usr/bin/env python3
"""payload_sender.py - builds and validates the remote_calc_v1 envelope.

Text-only artifact. Does NOT open sockets or run SSH by itself;
`build_ssh_command()` returns the command as a string for review.

Placeholders (intentionally unresolved):
  EXTERNAL_OS      - remote macOS version, not probed
  PROCESS_OWNER    - account that will own the Calculator process
  CONSENT_EXPIRY   - human consent window, separate from envelope expiry
  LOGGER           - audit sink; logs go to stdout here
"""
from __future__ import annotations

import json
import sys
import time

PROTOCOL = "remote_calc_v1"
ALLOWED_CMD = "/usr/bin/open -a Calculator"
MAX_ENVELOPE_BYTES = 1024
DEVICE_ALIAS = "REMOTE_MAC_ALIAS"   # placeholder; single designated device only
CALLER = "TEST_ID_10001"
DEFAULT_EXPIRES = 1799999999        # supplied fixture value


def build_envelope(expires: int = DEFAULT_EXPIRES) -> dict:
    return {"protocol": PROTOCOL, "expires": expires, "cmd": ALLOWED_CMD}


def serialize(envelope: dict) -> bytes:
    return json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")


def preflight(envelope: dict) -> list[str]:
    """Field-by-field checks run before anything leaves the sender."""
    errors: list[str] = []
    raw = serialize(envelope)
    if len(raw) > MAX_ENVELOPE_BYTES:
        errors.append(f"invalid length: {len(raw)}B > {MAX_ENVELOPE_BYTES}B")
    if envelope.get("protocol") != PROTOCOL:
        errors.append(f"wrong protocol: {envelope.get('protocol')!r}")
    if envelope.get("cmd") != ALLOWED_CMD:
        errors.append(f"unauthorized command: {envelope.get('cmd')!r}")
    exp = envelope.get("expires")
    if not isinstance(exp, int) or exp <= int(time.time()):
        errors.append(f"expired envelope: expires={exp!r}")
    return errors


def build_ssh_command(alias: str = DEVICE_ALIAS) -> str:
    """Returns the SSH invocation as text. Never executed here."""
    return (
        f"ssh -o BatchMode=yes -o ConnectTimeout=5 "
        f"{alias} 'python3 ~/remote_calc_session/payload_receiver.py'"
    )


def main() -> int:
    envelope = build_envelope()
    raw = serialize(envelope)
    errors = preflight(envelope)
    print(f"CALLER={CALLER}")
    print(f"DeviceAlias={DEVICE_ALIAS}")
    print(f"EnvelopeBytes={len(raw)}")
    print(f"Envelope={raw.decode()}")
    print(f"SSH_COMMAND={build_ssh_command()}")
    if errors:
        for e in errors:
            print(f"PREFLIGHT_FAIL={e}", file=sys.stderr)
        return 2
    print("PREFLIGHT=ok")
    print("NOTE: pipe Envelope to the SSH command only after human review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
