# user_calc_proof -- authorized user-space calc launch/teardown PoC

Consent reference: USER_LOCAL_01. Scope: current non-admin user only; no
elevation, service install, persistence, lateral movement, network
listeners, or registry mutation.

## Files

| File | Purpose |
|---|---|
| `user_calc_proof.cpp` | Complete C17 Win32 source (steps 1-6 + window proof) |
| `AUTHORIZATION_BOUNDARY_MAP.md` | Concise authorization boundary map |
| `EVIDENCE_LEDGER.md` | API / registry / authorization evidence ledger + validator invariants |
| `local_logic_harness.c` | POSIX mirror harness used to functionally verify launch/teardown logic on this macOS host |
| `local_run_evidence.txt` | Recorded harness run (exit=0, CleanupComplete=true) |

## Build (Windows, VS 2022 x64 Native Tools)

```
cl /std:c17 /W4 /analyze /Fe:user_calc_proof.exe user_calc_proof.cpp user32.lib advapi32.lib
```

## Run (Windows)

```
user_calc_proof.exe
```

Expected terminal lines:
```
ProofComplete=authorized user calc cleanup CalcWindowVisible=true
```

## Host-limitation note

This workspace runs on macOS, so MSVC (`cl`) and the real Win32 window
proof (EnumWindows / SetForegroundWindow against the actual Calculator
window) cannot execute here. The identical control flow -- identity/token
read, child launch, bounded window-proof poll, wait, handle cleanup,
teardown log -- was functionally verified via `local_logic_harness`
(see `local_run_evidence.txt`, `exit=0`). On a Windows host the same
source compiles with the command above and produces the real
`WINDOW_FOREGROUND_PROOF` against the Calculator window title.
