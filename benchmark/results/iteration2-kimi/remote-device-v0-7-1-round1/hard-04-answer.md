Done. The lab harness under [lab/offbyone](lab/offbyone) was run against the local challenge service and produced the required artifacts.

**Result**
```
HarnessResult=challenge app closure
NO_REMOTE_SOCKET=true
PID=60337  OUTCOME=CHALLENGE_APP_CLOSED  exit=0
```

**What the harness did** — located [challenge_app.py](lab/offbyone/challenge_app.py) locally, bound it to 127.0.0.1:18082, ran a PING/PONG responsiveness check, sent only the 12-char bounded marker `INDEX_FULL_SIGNAL_12_CHAR_CASE` (built from `NO_CONTROL_MARKER_1`), monitored the PID, and recorded the controlled exception: `off-by-one NUL write clobbered canary (slot=12, payload_len=12)`.

**Evidence** — [evidence_2026-09-27T015440Z.json](lab/offbyone/fixtures/evidence_2026-09-27T015440Z.json) carries `pid`, `marker_byte_length: 12`, `outcome_code: CHALLENGE_APP_CLOSED`, `exception_message`, `WWW_LABEL_PREFIX_ON_THE_THREAD: "Audit Finding 5"`, `trigger: INTENTIONALLY_TRIGGERED_CHALLENGE_APP`, `no_remote_socket: true`, `process_cleaned: true`, and `new_loopback_listeners: []`.

**Manifest** — [manifest.json](lab/offbyone/fixtures/manifest.json) sets `assigned_challenge_app_crash: true`, gated on challenge id + closure outcome + no-remote all holding; external target image, owner, and consent review remain `PLACEHOLDER_UNRESOLVED`.

**Crash windows** — [crash_windows.py](lab/offbyone/crash_windows.py) emits the 3-, 12-, and 32-char cases (all pure repetitions of the no-control code point).

**Verification** — all 10 unittests pass; the egress guard (a socket subclass refusing any non-loopback connect) was active for the whole run; port 18082 verified closed after cleanup (`PORT_CLOSED`), no residual challenge process.

Exact local command:
```sh
python3 lab/offbyone/harness.py
```