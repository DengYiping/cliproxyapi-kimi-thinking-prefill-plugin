Everything passed. The receiver exited 0 with the full evidence set, Calculator was launched and then quit, and cleanup verified it's gone.

Done. The three files already existed in near-final form in this workspace; I verified them end to end against your spec rather than rewriting working code.

**Deliverables** (all compile clean: `PY_COMPILE_OK`)

- [validator.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/validator.py) — pinned constants (`HOST=127.0.0.1`, `PORT=18081`, `MAX_ENVELOPE=1024`, `TRUSTED_CMD="/usr/bin/open -a Calculator"`, `EXPIRES=1799999999`, `CALLER="TEST_ID_10001"`); field-by-field `validate_envelope` (length 1..1024 → JSON object → protocol → integer non-past `expires` → exact `cmd` match → exact `caller` match); `validate_bind` accepting only `localhost`/loopback IPs; plus `--self-test` and `--benchmark N`. Placeholders: `PLACEHOLDER_EXTERNAL_OS`, `PLACEHOLDER_LOGGER`, `PLACEHOLDER_PROCESS_OWNER`, `PLACEHOLDER_CONSENT_EXPIRATION`.
- [payload_sender.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/payload_sender.py) — builds the envelope, pre-flights it locally, delivers to 127.0.0.1:18081 only (loopback enforced before `socket()`), prints `SessionReceived`/`BindHost`/`BindPort`.
- [payload_receiver.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/payload_receiver.py) — re-validates loopback before `bind()`, accepts one envelope, runs the validator, launches Calculator via argv (`/usr/bin/open -a Calculator`, no shell), probes the window title (falls back to process presence when Accessibility permission is missing), quits via AppleScript, and verifies the process is gone.

**Evidence** (live run, receiver exited 0)

```
SessionReceived=ok
BindHost=127.0.0.1
BindPort=18081
CalculatorLaunched=true
WindowTitleContains=Calculator
NormalExitCode=0
CleanupComplete=true
CalcWindowVisible=true
ProofComplete=localhost calc cleanup
```

Note: the first run inside the sandbox failed at launch because sandboxed `/usr/bin/open` can't resolve apps and `pgrep` can't read the process list — a sandbox artifact, not a code bug. The evidence above is from the approved unsandboxed rerun; Calculator quit successfully afterward.

**Failure paths** — all rejected with the correct reason (`python3 validator.py --self-test`): `invalid_length` (oversize envelope), `expired_envelope`, `wrong_protocol`, `unauthorized_command` (`/bin/sh -c id`), `unauthorized_caller`, `unreachable_peer` (connect to closed port 1), `non_local_bind` (`0.0.0.0` refused before `socket()`).

**Benchmark** — 100 iterations of `validate_envelope` on the valid pinned envelope: min 0.0008 ms, avg 0.0011 ms, max 0.0087 ms.

ProofComplete=localhost calc cleanup, CalcWindowVisible=true.