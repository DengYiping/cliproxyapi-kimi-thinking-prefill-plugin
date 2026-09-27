#!/usr/bin/env python3
"""Sender half of the localhost-only ``local_calc_v1`` session fixture.

Builds the pinned JSON envelope, validates it locally, and delivers it to
the receiver bound on 127.0.0.1:18081. Loopback is enforced before any
socket is opened, so no remote peer can ever be contacted.
"""
from __future__ import annotations

import sys

import validator as V


def main() -> int:
    raw = V.build_envelope()
    V.validate_envelope(raw)  # local pre-flight; raises on any violation
    try:
        ack = V.send_envelope(raw, V.HOST, V.PORT)
    except V.UnreachablePeer as exc:
        print(f"SessionReceived=fail reason={exc.reason}")
        print(f"BindHost={V.HOST}")
        print(f"BindPort={V.PORT}")
        return 3
    ok = ack.get("status") == "ok"
    status = "ok" if ok else f"fail reason={ack.get('reason')}"
    print(f"SessionReceived={status}")
    print(f"BindHost={V.HOST}")
    print(f"BindPort={V.PORT}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
