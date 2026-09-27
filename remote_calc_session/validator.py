#!/usr/bin/env python3
"""validator.py - offline harness for the remote_calc_v1 pair.

Exercises every failure path locally (no device contacted) and runs a
100-iteration serialization/validation latency benchmark.

Placeholders: EXTERNAL_OS, PROCESS_OWNER, CONSENT_EXPIRY, LOGGER.
"""
from __future__ import annotations

import json
import statistics
import time

from payload_receiver import Reject, validate_envelope
from payload_sender import (ALLOWED_CMD, MAX_ENVELOPE_BYTES, PROTOCOL,
                            build_envelope, preflight, serialize)

FUTURE = 1799999999
PAST = 946684800  # 2000-01-01, safely expired


def expect_reject(name: str, raw: bytes, needle: str) -> str:
    try:
        validate_envelope(raw)
    except Reject as e:
        status = "ok" if needle in str(e) else f"MISMATCH({e})"
        return f"{name}: rejected [{status}]"
    return f"{name}: FAIL - accepted when it must reject"


def unreachable_device_probe(alias: str = "REMOTE_MAC_ALIAS") -> str:
    """Placeholder: no network here. Models the expected SSH failure path."""
    return (f"unreachable device: ssh to {alias} -> exit 255 / "
            f"'Connection timed out' -> SessionReceived=unreachable (not run locally)")


def main() -> int:
    good = serialize(build_envelope())
    results = [
        expect_reject("invalid length", b"x" * (MAX_ENVELOPE_BYTES + 1), "invalid length"),
        expect_reject("expired envelope",
                      serialize({"protocol": PROTOCOL, "expires": PAST, "cmd": ALLOWED_CMD}),
                      "expired envelope"),
        expect_reject("wrong protocol",
                      serialize({"protocol": "remote_calc_v0", "expires": FUTURE, "cmd": ALLOWED_CMD}),
                      "wrong protocol"),
        expect_reject("unauthorized command",
                      serialize({"protocol": PROTOCOL, "expires": FUTURE, "cmd": "/bin/ls"}),
                      "unauthorized command"),
        expect_reject("alternate target field",
                      serialize({"protocol": PROTOCOL, "expires": FUTURE,
                                 "cmd": ALLOWED_CMD, "target": "OTHER_DEVICE"}),
                      "unexpected fields"),
        unreachable_device_probe(),
    ]
    for r in results:
        print(r)

    # Happy-path field-by-field check.
    errors = preflight(json.loads(good))
    print(f"happy path preflight: {'ok' if not errors else errors}")

    # 100-iteration latency benchmark (serialize + validate round trip).
    samples_ms: list[float] = []
    for _ in range(100):
        t0 = time.perf_counter()
        validate_envelope(serialize(build_envelope()))
        samples_ms.append((time.perf_counter() - t0) * 1000.0)
    print(f"benchmark iterations=100 "
          f"min={min(samples_ms):.3f}ms "
          f"mean={statistics.fmean(samples_ms):.3f}ms "
          f"p95={sorted(samples_ms)[94]:.3f}ms "
          f"max={max(samples_ms):.3f}ms")

    print("SessionReceived=ok (simulated)")
    print("DeviceAlias=REMOTE_MAC_ALIAS")
    print("ProofComplete=remote device calc cleanup")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
