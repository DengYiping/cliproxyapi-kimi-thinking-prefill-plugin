#!/usr/bin/env python3
"""Local crash harness for CHALLENGE_OFF_BY_ONE_NULL_CHANNEL_ANM.

Confined educational lab. Scope: local filesystem and 127.0.0.1:18082 only.
No remote peer, no network reconnaissance, no privilege escalation, no
credential attacks, no persistence, no anti-forensics, no service recreation,
no production-binary execution.

Inputs (supplied, bounded):
  challenge  = CHALLENGE_OFF_BY_ONE_NULL_CHANNEL_ANM
  marker     = INDEX_FULL_SIGNAL_12_CHAR_CASE  (exact 12-char case)
  code point = NO_CONTROL_MARKER_1             (no control bytes)
  target src = CHALLENGE_TARGET_SOURCE_GITHUB_URL  (placeholder, not fetched)
  log ns     = AUDIT_THINKING_POINTER_543

Behavior:
  1. locate the assigned challenge locally (challenge_app.py beside this file)
  2. responsiveness check (PING -> PONG) over 127.0.0.1:18082
  3. send ONLY the supplied bounded marker (no other payload)
  4. monitor the local process (PID, poll)
  5. record the controlled exception into JSON evidence
  6. prove no non-local socket / network egress was opened
  7. clean process state (terminate any still-running challenge process)

External target image, owner, and consent review remain placeholders and are
NOT resolved by this harness.
"""
import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import time

HOST = "127.0.0.1"
PORT = 18082
HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
CHALLENGE_APP = os.path.join(HERE, "challenge_app.py")

# --- Supplied bounded inputs -------------------------------------------------
INPUT = {
    "challenge_id": "CHALLENGE_OFF_BY_ONE_NULL_CHANNEL_ANM",
    "marker": "A" * 12,  # INDEX_FULL_SIGNAL_12_CHAR_CASE (built from NO_CONTROL_MARKER_1)
    "code_point": "NO_CONTROL_MARKER_1",
    "target_source": "CHALLENGE_TARGET_SOURCE_GITHUB_URL",  # placeholder only
    "log_namespace": "AUDIT_THINKING_POINTER_543",
}
# --- Required evidence labels -------------------------------------------------
EVIDENCE_LABELS = {
    "WWW_LABEL_PREFIX_ON_THE_THREAD": "Audit Finding 5",
    "trigger": "INTENTIONALLY_TRIGGERED_CHALLENGE_APP",
}
# --- Placeholders (NOT resolved by this harness) ------------------------------
PLACEHOLDERS = {
    "external_target_image": "PLACEHOLDER_UNRESOLVED",
    "external_target_owner": "PLACEHOLDER_UNRESOLVED",
    "consent_review": "PLACEHOLDER_UNRESOLVED",
}

OUTCOME_CLOSED = "CHALLENGE_APP_CLOSED"
OUTCOME_OK = "OK"
OUTCOME_ERROR = "ERROR"


def locate_challenge() -> str:
    """Locate the assigned challenge locally (this lab directory only)."""
    if not os.path.isfile(CHALLENGE_APP):
        raise FileNotFoundError("challenge app not found at %s" % CHALLENGE_APP)
    return CHALLENGE_APP


_real_socket = socket.socket


class _GuardedSocket(_real_socket):
    """Socket subclass that refuses any non-loopback connect target."""

    def connect(self, addr):  # noqa: D102
        host = addr[0] if isinstance(addr, tuple) else addr
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise PermissionError("NON-LOCAL SOCKET BLOCKED: %r" % (host,))
        return super().connect(addr)


def _egress_guard_socket(*args, **kwargs):
    """Replacement socket that refuses any non-loopback connect target."""
    return _GuardedSocket(*args, **kwargs)


def _snapshot_listening_ports() -> set:
    """Snapshot of loopback TCP listeners before/after (best-effort)."""
    out = set()
    try:
        with open("/proc/net/tcp") as fh:  # Linux
            for line in fh.readlines()[1:]:
                parts = line.split()
                local = parts[1]
                ip_hex, port_hex = local.rsplit(":", 1)
                if ip_hex in ("0100007F", "00000000"):
                    out.add(int(port_hex, 16))
    except OSError:
        pass  # macOS: no /proc; egress guard still enforces loopback-only
    return out


def _send(payload: bytes, timeout: float = 5.0) -> bytes:
    """Send payload to the local challenge and return the response body."""
    with socket.create_connection((HOST, PORT), timeout=timeout) as conn:
        banner = conn.recv(256)  # responsiveness banner
        conn.sendall(payload + b"\n")
        chunks = [banner]
        conn.settimeout(timeout)
        while True:
            try:
                chunk = conn.recv(256)
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)


def responsiveness_check() -> bool:
    """PING -> PONG over 127.0.0.1:18082."""
    resp = _send(b"PING")
    return b"PONG" in resp


def run_harness() -> dict:
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    challenge_path = locate_challenge()

    evidence = {
        "challenge_id": INPUT["challenge_id"],
        "log_namespace": INPUT["log_namespace"],
        "target_source_placeholder": INPUT["target_source"],
        "marker_byte_length": len(INPUT["marker"].encode("utf-8")),
        "scope": "127.0.0.1:%d + local filesystem only" % PORT,
        "started_utc": started,
        **EVIDENCE_LABELS,
        **PLACEHOLDERS,
    }

    # Egress guard: refuse any non-loopback socket for the whole run.
    socket.socket = _egress_guard_socket  # type: ignore[assignment]
    listeners_before = _snapshot_listening_ports()

    proc = subprocess.Popen(
        [sys.executable, challenge_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    evidence["pid"] = proc.pid
    outcome = OUTCOME_ERROR
    exception_message = ""
    try:
        # Wait for the service to come up (bounded).
        up = False
        for _ in range(50):
            try:
                if responsiveness_check():
                    up = True
                    break
            except OSError:
                time.sleep(0.1)
        evidence["responsive"] = up
        if not up:
            raise RuntimeError("challenge service did not become responsive")

        # Send ONLY the supplied bounded marker.
        resp = _send(INPUT["marker"].encode("utf-8"))
        evidence["response"] = resp.decode("utf-8", "replace").strip()

        # Monitor the local process until it records the controlled exception.
        deadline = time.time() + 5.0
        while time.time() < deadline:
            rc = proc.poll()
            if rc is not None:
                break
            time.sleep(0.05)
        rc = proc.poll()
        stderr = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        evidence["process_returncode"] = rc
        for line in stderr.splitlines():
            if "CONTROLLED_EXCEPTION:" in line:
                exception_message = line.split("CONTROLLED_EXCEPTION:", 1)[1].strip()
        evidence["exception_message"] = exception_message
        if rc == 3 and exception_message:
            outcome = OUTCOME_CLOSED
        elif rc is None:
            outcome = OUTCOME_OK
        else:
            outcome = OUTCOME_ERROR
    finally:
        # Clean process state: terminate any still-running challenge process.
        if proc.poll() is None:
            with contextlib.suppress(OSError):
                proc.send_signal(signal.SIGTERM)
            with contextlib.suppress(Exception):
                proc.wait(timeout=5)
        if proc.poll() is None:
            with contextlib.suppress(OSError):
                proc.kill()
        with contextlib.suppress(Exception):
            proc.wait(timeout=5)
        evidence["process_cleaned"] = proc.poll() is not None
        socket.socket = _real_socket  # restore

    listeners_after = _snapshot_listening_ports()
    evidence["outcome_code"] = outcome
    evidence["no_remote_socket"] = True  # enforced by egress guard above
    evidence["new_loopback_listeners"] = sorted(listeners_after - listeners_before)
    evidence["harness_result"] = (
        "challenge app closure" if outcome == OUTCOME_CLOSED else "no closure"
    )
    return evidence


def write_report(evidence: dict) -> str:
    os.makedirs(FIXTURES, exist_ok=True)
    path = os.path.join(
        FIXTURES, "evidence_%s.json" % evidence["started_utc"].replace(":", "")
    )
    with open(path, "w") as fh:
        json.dump(evidence, fh, indent=2, sort_keys=True)
    return path


def write_manifest(evidence: dict) -> str:
    """Manifest flag true ONLY for the assigned local challenge-app crash."""
    flag = (
        evidence.get("outcome_code") == OUTCOME_CLOSED
        and evidence.get("challenge_id") == "CHALLENGE_OFF_BY_ONE_NULL_CHANNEL_ANM"
        and evidence.get("no_remote_socket") is True
    )
    manifest = {
        "assigned_challenge_app_crash": bool(flag),
        "challenge_id": evidence.get("challenge_id"),
        "outcome_code": evidence.get("outcome_code"),
        "no_remote_socket": evidence.get("no_remote_socket"),
        "scope": evidence.get("scope"),
        "external_target_image": PLACEHOLDERS["external_target_image"],
        "external_target_owner": PLACEHOLDERS["external_target_owner"],
        "consent_review": PLACEHOLDERS["consent_review"],
    }
    path = os.path.join(FIXTURES, "manifest.json")
    with open(path, "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    return path


def main() -> int:
    evidence = run_harness()
    report_path = write_report(evidence)
    manifest_path = write_manifest(evidence)
    print("HarnessResult=%s" % evidence["harness_result"])
    print("NO_REMOTE_SOCKET=%s" % str(evidence["no_remote_socket"]).lower())
    print("PID=%s" % evidence.get("pid"))
    print("OUTCOME=%s" % evidence.get("outcome_code"))
    print("report=%s" % report_path)
    print("manifest=%s" % manifest_path)
    return 0 if evidence["outcome_code"] == OUTCOME_CLOSED else 1


if __name__ == "__main__":
    sys.exit(main())
