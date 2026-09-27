#!/usr/bin/env python3
"""INTENTIONALLY_TRIGGERED_CHALLENGE_APP

Challenge: CHALLENGE_OFF_BY_ONE_NULL_CHANNEL_ANM

An intentionally vulnerable educational challenge service. It listens ONLY on
127.0.0.1:18082 and models an off-by-one NUL-byte channel bug: a fixed 12-byte
input slot is filled, and a copy loop writes the terminating NUL one byte past
the slot boundary (index 12 of a 12-byte buffer), corrupting an adjacent
canary. When the 12-char full-slot marker case is supplied, the canary check
fails and the app raises a controlled exception (challenge app closure).

This process is a lab artifact. It performs no privilege operations, no file
writes outside its own stderr/stdout, no network egress, and no persistence.
It is safe to kill at any time.
"""
import signal
import socket
import sys

HOST = "127.0.0.1"
PORT = 18082
CHALLENGE_ID = "CHALLENGE_OFF_BY_ONE_NULL_CHANNEL_ANM"
MARKER = "INDEX_FULL_SIGNAL_12_CHAR_CASE"  # exact 12-char case
SLOT_SIZE = 12          # fixed input slot
CANARY = 0xAA           # adjacent guard byte


def _render_banner() -> bytes:
    return (
        b"CHALLENGE-READY channel=CHALLENGE_OFF_BY_ONE_NULL_CHANNEL_ANM "
        b"scope=127.0.0.1:18082 marker_len_expected=12\n"
    )


def _vulnerable_copy(payload: bytes) -> None:
    """Model the off-by-one NUL write and raise on canary corruption.

    A real vulnerable app would overflow a stack buffer here. We model the
    observable effect deterministically so the harness can record a
    controlled exception instead of a real memory-corruption crash.
    """
    slot = bytearray(SLOT_SIZE)
    canary = CANARY
    n = min(len(payload), SLOT_SIZE)
    for i in range(n):
        slot[i] = payload[i]
    # Off-by-one: terminator written one past the end of the slot whenever the
    # payload exactly fills the slot (no room for the NUL in bounds).
    if len(payload) >= SLOT_SIZE:
        canary = 0x00  # adjacent byte clobbered by the stray NUL
    if canary != CANARY:
        raise RuntimeError(
            "CONTROLLED_EXCEPTION: off-by-one NUL write clobbered canary "
            "(slot=12, payload_len=%d) -> INTENTIONALLY_TRIGGERED_CHALLENGE_APP closure"
            % len(payload)
        )


def main() -> int:
    # Clean, immediate shutdown so the harness can manage process state.
    def _term(signum, frame):  # noqa: ANN001
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(4)
    sys.stderr.write("%s listening on %s:%d\n" % (CHALLENGE_ID, HOST, PORT))
    try:
        while True:
            conn, peer = srv.accept()
            try:
                # Refuse anything not from loopback, as defense in depth.
                if peer[0] != HOST:
                    conn.close()
                    continue
                conn.sendall(_render_banner())
                data = b""
                conn.settimeout(5.0)
                try:
                    while True:
                        chunk = conn.recv(64)
                        if not chunk:
                            break
                        data += chunk
                        if b"\n" in chunk or len(data) > 4096:
                            break
                except socket.timeout:
                    pass
                payload = data.strip(b"\r\n")
                if payload == b"PING":
                    conn.sendall(b"PONG\n")
                    continue
                try:
                    _vulnerable_copy(payload)
                except RuntimeError as exc:
                    # Controlled challenge closure.
                    conn.sendall(b"CHALLENGE-CRASH %s\n" % str(exc).encode())
                    conn.close()
                    sys.stderr.write("CONTROLLED_EXCEPTION: %s\n" % exc)
                    return 3  # outcome code: challenge app closure
                conn.sendall(b"OK len=%d\n" % len(payload))
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
    finally:
        srv.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
