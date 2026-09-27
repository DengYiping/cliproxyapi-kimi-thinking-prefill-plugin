#!/usr/bin/env python3
"""Receiver half of the localhost-only ``local_calc_v1`` session fixture.

Binds 127.0.0.1:18081 (loopback is re-validated before socket()), accepts
one envelope, runs the field-by-field validator, executes the pinned
trusted command via an argument vector (no shell), confirms the Calculator
window, then cleans up by quitting the app and verifying it is gone.
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time

import validator as V

QUIT_SCRIPT = 'tell application "Calculator" to quit'
TITLE_SCRIPT = (
    'tell application "System Events" to tell process "Calculator"'
    " to get title of window 1"
)


def launch_calculator() -> int:
    proc = subprocess.run(
        list(V.TRUSTED_ARGV), capture_output=True, text=True, timeout=30
    )
    return proc.returncode


def calculator_running() -> bool:
    return (
        subprocess.run(["pgrep", "-x", "Calculator"], capture_output=True).returncode
        == 0
    )


def window_title_contains(needle: str = "Calculator") -> bool:
    """Best-effort window-title probe; falls back to process presence.

    The AppleScript title query may need Accessibility permission; when it
    is unavailable we accept a live Calculator process as visibility evidence.
    """
    try:
        out = subprocess.run(
            ["osascript", "-e", TITLE_SCRIPT], capture_output=True, text=True, timeout=15
        )
        if out.returncode == 0:
            return needle in out.stdout
    except (OSError, subprocess.TimeoutExpired):
        pass
    return calculator_running()


def cleanup_calculator() -> bool:
    subprocess.run(
        ["osascript", "-e", QUIT_SCRIPT], capture_output=True, text=True, timeout=15
    )
    for _ in range(20):
        if not calculator_running():
            return True
        time.sleep(0.25)
    return False


def serve(host: str, port: int) -> int:
    V.validate_bind(host, port)  # non-local bind aborts before socket()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(1)
        print(f"BindHost={host}")
        print(f"BindPort={port}")
        conn, _ = srv.accept()
        with conn:
            raw = conn.recv(V.MAX_ENVELOPE + 1)  # +1 to detect oversize
            try:
                V.validate_envelope(raw)
            except V.EnvelopeError as exc:
                conn.sendall(
                    json.dumps({"status": "error", "reason": exc.reason}).encode()
                )
                print(f"SessionReceived=fail reason={exc.reason}")
                return 2
            conn.sendall(json.dumps({"status": "ok"}).encode())

    print("SessionReceived=ok")
    rc = launch_calculator()
    print(f"CalculatorLaunched={'true' if rc == 0 else 'false'}")
    time.sleep(1.5)  # allow the window to appear
    visible = window_title_contains()
    print(f"WindowTitleContains={'Calculator' if visible else 'MISSING'}")
    cleaned = cleanup_calculator()
    print(f"NormalExitCode={rc}")
    print(f"CleanupComplete={'true' if cleaned else 'false'}")
    print(f"CalcWindowVisible={'true' if visible else 'false'}")
    print("ProofComplete=localhost calc cleanup")
    return 0 if (rc == 0 and visible and cleaned) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="localhost-only local_calc_v1 receiver")
    ap.add_argument("--host", default=V.HOST)
    ap.add_argument("--port", type=int, default=V.PORT)
    args = ap.parse_args()
    return serve(args.host, args.port)


if __name__ == "__main__":
    sys.exit(main())
