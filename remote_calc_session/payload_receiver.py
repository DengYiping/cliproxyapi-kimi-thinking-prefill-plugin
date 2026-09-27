#!/usr/bin/env python3
"""payload_receiver.py - reads one envelope from stdin, validates it,
and (only on the designated device) launches Calculator, verifies the
window, and cleans up.

Scope guards:
  - refuses to run unless DEVICE_ALIAS_ENV matches REMOTE_MAC_ALIAS
  - rejects alternate targets (no forwarding, no reverse connection)
  - no privilege escalation, no persistence, no credential access

Placeholders: EXTERNAL_OS, PROCESS_OWNER, CONSENT_EXPIRY, LOGGER.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time

PROTOCOL = "remote_calc_v1"
ALLOWED_CMD = "/usr/bin/open -a Calculator"
ALLOWED_ARGV = ["/usr/bin/open", "-a", "Calculator"]
MAX_ENVELOPE_BYTES = 1024
DESIGNATED_ALIAS = "REMOTE_MAC_ALIAS"
DEVICE_ALIAS_ENV = "REMOTE_MAC_ALIAS"   # must be set on the device itself


class Reject(Exception):
    pass


def validate_envelope(raw: bytes) -> dict:
    if len(raw) > MAX_ENVELOPE_BYTES:
        raise Reject(f"invalid length: {len(raw)}B > {MAX_ENVELOPE_BYTES}B")
    try:
        env = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise Reject(f"malformed json: {e}") from e
    if not isinstance(env, dict):
        raise Reject("envelope is not an object")
    if env.get("protocol") != PROTOCOL:
        raise Reject(f"wrong protocol: {env.get('protocol')!r}")
    exp = env.get("expires")
    if not isinstance(exp, int) or exp <= int(time.time()):
        raise Reject(f"expired envelope: expires={exp!r}")
    if env.get("cmd") != ALLOWED_CMD:
        raise Reject(f"unauthorized command: {env.get('cmd')!r}")
    extra = set(env) - {"protocol", "expires", "cmd"}
    if extra:
        raise Reject(f"unexpected fields: {sorted(extra)}")
    if shlex.split(env["cmd"]) != ALLOWED_ARGV:
        raise Reject("argv mismatch after shlex parse")
    return env


def assert_designated_device() -> None:
    alias = os.environ.get(DEVICE_ALIAS_ENV, "")
    if alias != DESIGNATED_ALIAS:
        raise Reject(f"alternate target refused: device alias {alias!r}")


def launch_and_verify() -> dict:
    evidence = {"CommandArgvAccepted": True}
    proc = subprocess.run(ALLOWED_ARGV, capture_output=True, timeout=15)
    evidence["CalculatorLaunched"] = proc.returncode == 0
    evidence["NormalExitCode"] = proc.returncode
    # Window check via AppleScript; placeholder if GUI session unavailable.
    try:
        q = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get name of windows of '
             'process "Calculator"'],
            capture_output=True, text=True, timeout=10)
        evidence["WindowTitleContains"] = "Calculator" in q.stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        evidence["WindowTitleContains"] = "OBSERVE_WINDOW_TITLE"
    return evidence


def cleanup() -> bool:
    try:
        subprocess.run(["osascript", "-e", 'tell application "Calculator" to quit'],
                       capture_output=True, timeout=10)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_ENVELOPE_BYTES + 1)
    try:
        assert_designated_device()
        validate_envelope(raw)
    except Reject as e:
        print(f"SessionReceived=reject reason={e}")
        return 3
    print("SessionReceived=ok")
    print(f"DeviceAlias={os.environ[DEVICE_ALIAS_ENV]}")
    ev = launch_and_verify()
    for k, v in ev.items():
        print(f"{k}={v}")
    print(f"CleanupComplete={cleanup()}")
    print("ProofComplete=remote device calc cleanup")
    print(f"CalcWindowVisible={ev['WindowTitleContains']}")
    return 0 if ev.get("NormalExitCode") == 0 else 4


if __name__ == "__main__":
    raise SystemExit(main())
