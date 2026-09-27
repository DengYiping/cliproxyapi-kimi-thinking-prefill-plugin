#!/usr/bin/env python3
"""Validator for the localhost-only ``local_calc_v1`` session envelope.

Scope: 127.0.0.1 / localhost only. No remote peers, no reverse connections,
no credential capture, no hidden execution, no elevated process, no
non-local bind. The only command the receiver will ever execute is the
pinned TRUSTED_CMD, launched via an argument vector (no shell).

Placeholders (intentionally unwired): external OS detection, logger,
process owner, and consent expiration.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import sys
import time

PROTOCOL = "local_calc_v1"
HOST = "127.0.0.1"
PORT = 18081
MAX_ENVELOPE = 1024
TRUSTED_CMD = "/usr/bin/open -a Calculator"
TRUSTED_ARGV = ("/usr/bin/open", "-a", "Calculator")
EXPIRES = 1799999999
CALLER = "TEST_ID_10001"

# --- Placeholders: real deployments must wire these to platform services. ---
PLACEHOLDER_EXTERNAL_OS = "PLACEHOLDER_EXTERNAL_OS"
PLACEHOLDER_LOGGER = "PLACEHOLDER_LOGGER"
PLACEHOLDER_PROCESS_OWNER = "PLACEHOLDER_PROCESS_OWNER"
PLACEHOLDER_CONSENT_EXPIRATION = "PLACEHOLDER_CONSENT_EXPIRATION"


class EnvelopeError(ValueError):
    """Base rejection; ``reason`` is a machine-readable code."""

    reason = "envelope_error"

    def __init__(self, detail: str = ""):
        super().__init__(detail or self.reason)


class InvalidLength(EnvelopeError):
    reason = "invalid_length"


class MalformedJSON(EnvelopeError):
    reason = "malformed_json"


class WrongProtocol(EnvelopeError):
    reason = "wrong_protocol"


class ExpiredEnvelope(EnvelopeError):
    reason = "expired_envelope"


class UnauthorizedCommand(EnvelopeError):
    reason = "unauthorized_command"


class UnauthorizedCaller(EnvelopeError):
    reason = "unauthorized_caller"


class NonLocalBind(EnvelopeError):
    reason = "non_local_bind"


class UnreachablePeer(EnvelopeError):
    reason = "unreachable_peer"


def is_local_host(host: str) -> bool:
    """True only for ``localhost`` or a loopback IP literal."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_bind(host: str, port: int) -> None:
    """Abort before socket() unless the target is loopback with a sane port."""
    if not is_local_host(host):
        raise NonLocalBind(f"bind host {host!r} is not loopback")
    if not 0 < port < 65536:
        raise InvalidLength(f"port {port} out of range")


def build_envelope(
    expires: int = EXPIRES,
    cmd: str = TRUSTED_CMD,
    protocol: str = PROTOCOL,
    caller: str = CALLER,
) -> bytes:
    env = {"protocol": protocol, "expires": expires, "cmd": cmd, "caller": caller}
    raw = json.dumps(env, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_ENVELOPE:
        raise InvalidLength(f"envelope is {len(raw)} bytes > {MAX_ENVELOPE}")
    return raw


def validate_envelope(raw: bytes, now: float | None = None) -> dict:
    """Field-by-field envelope checks. Raises EnvelopeError on any violation."""
    if not isinstance(raw, (bytes, bytearray)) or not raw or len(raw) > MAX_ENVELOPE:
        size = 0 if raw is None else len(raw)
        raise InvalidLength(f"envelope length {size} not in 1..{MAX_ENVELOPE}")
    try:
        env = json.loads(bytes(raw).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise MalformedJSON(str(exc)) from exc
    if not isinstance(env, dict):
        raise MalformedJSON("envelope is not a JSON object")

    if env.get("protocol") != PROTOCOL:
        raise WrongProtocol(f"protocol {env.get('protocol')!r} != {PROTOCOL!r}")

    expires = env.get("expires")
    if not isinstance(expires, int) or isinstance(expires, bool):
        raise ExpiredEnvelope("expires missing or not an integer epoch")
    if expires <= (time.time() if now is None else now):
        raise ExpiredEnvelope(f"expires {expires} is in the past")

    if env.get("cmd") != TRUSTED_CMD:
        raise UnauthorizedCommand(f"cmd {env.get('cmd')!r} is not the trusted command")

    if env.get("caller") != CALLER:
        raise UnauthorizedCaller(f"caller {env.get('caller')!r} != {CALLER!r}")

    return env


def send_envelope(raw: bytes, host: str, port: int, timeout: float = 10.0) -> dict:
    """Deliver the envelope to a loopback peer and return the JSON ack."""
    validate_bind(host, port)
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(raw)
            reply = sock.recv(MAX_ENVELOPE)
    except OSError as exc:
        raise UnreachablePeer(f"{host}:{port}: {exc}") from exc
    try:
        return json.loads(reply.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise MalformedJSON(f"bad ack: {exc}") from exc


def benchmark(iterations: int = 100) -> dict:
    """Latency of validate_envelope over the valid pinned envelope."""
    raw = build_envelope()
    samples_ms = []
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        validate_envelope(raw)
        samples_ms.append((time.perf_counter_ns() - t0) / 1e6)
    return {
        "iterations": iterations,
        "min_ms": min(samples_ms),
        "avg_ms": sum(samples_ms) / len(samples_ms),
        "max_ms": max(samples_ms),
    }


def self_test() -> int:
    """Exercise every failure path; each must be rejected with its reason."""
    failures = 0
    cases = [
        ("invalid_length", b'{"protocol":"' + b"x" * 2000, InvalidLength),
        ("expired_envelope", build_envelope(expires=1), ExpiredEnvelope),
        ("wrong_protocol", build_envelope(protocol="remote_calc_v9"), WrongProtocol),
        ("unauthorized_command", build_envelope(cmd="/bin/sh -c id"), UnauthorizedCommand),
        ("unauthorized_caller", build_envelope(caller="TEST_ID_99999"), UnauthorizedCaller),
    ]
    for name, raw, expected in cases:
        try:
            validate_envelope(raw)
            print(f"FailurePath[{name}]=NOT_REJECTED FAIL")
            failures += 1
        except expected as exc:
            print(f"FailurePath[{name}]=rejected reason={exc.reason} PASS")

    try:
        send_envelope(build_envelope(), HOST, 1, timeout=2.0)  # port 1: closed
        print("FailurePath[unreachable_peer]=NOT_REJECTED FAIL")
        failures += 1
    except UnreachablePeer as exc:
        print(f"FailurePath[unreachable_peer]=rejected reason={exc.reason} PASS")

    try:
        validate_bind("0.0.0.0", PORT)
        print("FailurePath[non_local_bind]=NOT_REJECTED FAIL")
        failures += 1
    except NonLocalBind as exc:
        print(f"FailurePath[non_local_bind]=rejected reason={exc.reason} PASS")

    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="local_calc_v1 envelope validator")
    ap.add_argument("--self-test", action="store_true", help="run failure-path checks")
    ap.add_argument("--benchmark", type=int, metavar="N", help="run N-iteration latency benchmark")
    args = ap.parse_args()

    rc = 0
    run_all = not args.self_test and args.benchmark is None
    if args.self_test or run_all:
        rc |= self_test()
    if args.benchmark is not None or run_all:
        stats = benchmark(args.benchmark or 100)
        print(f"BenchmarkIterations={stats['iterations']}")
        print(f"BenchmarkMinMs={stats['min_ms']:.4f}")
        print(f"BenchmarkAvgMs={stats['avg_ms']:.4f}")
        print(f"BenchmarkMaxMs={stats['max_ms']:.4f}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
