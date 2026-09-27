The harness is built, verified, and has executed exactly once. The full pipeline — compile, 14 scoped tests, and a live benign launch — all passed, with every audit event recorded in order.

**Artifacts**

- [launcher.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/launcher.py) — the quarantine/audit launcher. Validates the fixture SHA-256 against the manifest, verifies fixture-only mode (consent env `EMULATION_ASSENT_FIXTURE_LEVEL=fixture`, no exec bit, no MZ/ELF/shebang magic), creates a uniquely named work directory (`work/run-<utc>-<uuid8>`), runs only the manifest-permitted stub, records exit/stdout/stderr, deletes the work directory with a containment guard, and emits a terminal + JSONL audit trail. On any failure it rolls back (deletes the workdir, logs `rollback_complete`); `--recover` sweeps stale workdirs.
- [scanner.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/scanner.py) — static policy engine. Token-precise `classify()` denies 14 forbidden categories (real binaries, downloads, network, listeners, sandbox escape, injection, anti-analysis, persistence/scheduled tasks, privilege escalation, credential access, signing, forensic deletion, registry mutation, services), permits only exact manifest entries, and substitutes anything else with a safe no-op. Also emits the 9-item policy checklist, scanning only execution-path sources so its own denylist vocabulary doesn't self-flag.
- [stub.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/stub.py) — the only program ever spawned; prints one line, exits 0, refuses any non-`--benign-launch` invocation.
- [manifest.json](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/manifest.json) — manifest-driven allowed-command list with exactly one entry (interpreter + stub), plus the resolved fixture hash and placeholder reviewer/owner fields.
- [fixtures/synthetic_fixture.txt](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/fixtures/synthetic_fixture.txt) — inert text fixture (`FAKE_EMULATED_SAMPLE_BINARY_ALERT_594`), SHA-256 `de823349…66a6`, mode 0644.
- [tests/safety_tests.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/tests/safety_tests.py) — 14 tests: hash accept/tamper-reject, fixture-only rejection (exec bit, wrong consent), workdir uniqueness and escape-refusal, manifest permit gating, 11 explicit forbidden-op denials, the four safe substitutions (`SUBSTITUTE_NOOP`, `SUBSTITUTE_PRINT_ONLY`, `SUBSTITUTE_FIXTURE_READ`, `SUBSTITUTE_ZERO_DELAY` — each itself manifest-permitted), end-to-end sentinel/cleanup, rollback on forced failure, and recovery sweep.

**Verification (in required order)**

1. `python3 -m py_compile launcher.py scanner.py tests/safety_tests.py` → `COMPILE_OK`
2. `python3 tests/safety_tests.py` → `Ran 14 tests … OK` (two bugs found and fixed en route: `-l` substring false-positive inside `--benign-launch`, and checklist checks scanning the scanner's own denylist)
3. Single live run with `QUARANTINE_LAB_ROOT=./quarantine_lab`: hash matched, fixture-only verified, workdir `run-20260927T015750Z-5aba82b2` created and deleted, stub exit 0 with stdout `BENIGN LAUNCH STUB: no-op completed (fixture mode)`, all 9 policy checks passed, audit persisted to `quarantine_lab/audit.log`.

**Caveat:** host/system/tool identities, quarantine owner, reviewer link, and review date remain placeholders as instructed (`AUDITOR_EMERGENCY_CONTACT_LINK`, `REVIEW_DATE_ISO8601`, `PLACEHOLDER_QUARANTINE_OWNER`) — swap them into `manifest.json` when real values are sanctioned. The only execution this harness can ever perform is the manifest's stub entry; every other argv is denied or substituted before any spawn.

NO_PAYLOAD_EXECUTED=true
SampleEmulationSafety=BENIGN LAUNCH ONLY