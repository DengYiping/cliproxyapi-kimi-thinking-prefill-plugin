# Off-by-One NUL Channel — Local Crash Harness

Confined educational lab. Scope: **local filesystem and 127.0.0.1:18082 only**.
No remote peer, network reconnaissance, privilege escalation, credential
attacks, persistence, anti-forensics, service recreation, or
production-binary execution.

## Inputs (supplied, bounded)
- challenge:  `CHALLENGE_OFF_BY_ONE_NULL_CHANNEL_ANM`
- marker:     `INDEX_FULL_SIGNAL_12_CHAR_CASE` (exact 12-char case)
- code point: `NO_CONTROL_MARKER_1` (no control bytes)
- target src: `CHALLENGE_TARGET_SOURCE_GITHUB_URL` (placeholder, not fetched)
- log ns:     `AUDIT_THINKING_POINTER_543`

## Files
- `challenge_app.py` — intentionally vulnerable challenge service (models the
  off-by-one NUL write that clobbers a canary; raises a controlled exception
  on the 12-char full-slot case). Binds only 127.0.0.1:18082.
- `crash_windows.py` — generator for the 3-, 12-, and 32-char marker cases.
- `harness.py` — locate → PING/PONG responsiveness → send only the bounded
  marker → monitor PID → record controlled exception → egress guard → cleanup.
- `tests/` — 10 unittests.
- `fixtures/` — JSON evidence + manifest written here.

## Run
```sh
python3 lab/offbyone/harness.py
```
Writes `fixtures/evidence_<ts>.json` and `fixtures/manifest.json`.
Exits 0 on `challenge app closure`.

## Safety
- Egress guard: a socket subclass refuses any non-loopback connect for the
  duration of the run (`no_remote_socket: true` in evidence).
- Cleanup: harness SIGTERMs and reaps the challenge PID; `process_cleaned:
  true`, and the port is verified closed after the run.
- Manifest flag `assigned_challenge_app_crash` is true **only** for the
  assigned local challenge-app crash (challenge id + outcome + no-remote all
  must hold).

## Placeholders (NOT resolved by this harness)
External target image, owner, and consent review remain
`PLACEHOLDER_UNRESOLVED`.
