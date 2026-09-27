# authorized_win64_calculator PoC

Concise overview / authorization assumptions: the target is an
isolated Windows 11 x64 lab VM that the requester explicitly owns
and controls. This is a user-visible "pop a calculator"-class
driver/client PoC using only documented Win32 calls. It opens its
OWN process token read-only (TOKEN_QUERY) to prove token state, then
launches the calculator as a child in the caller's session. No
injection, no privilege changes, no cross-session behavior.

## Exact Win32 call sequence
1. `GetCurrentProcessToken`  -- pseudo-handle to our token
2. `OpenProcessToken`        -- real TOKEN_QUERY handle
3. `GetTokenInformation`     -- TokenUser (proves token readable)
4. `CloseHandle`             -- token handle
5. `CreateProcessW`          -- launches `C:\Windows\System32\calc.exe`
6. `WaitForSingleObject`     -- blocks until calculator exits
7. `CloseHandle`             -- process handle (then thread handle)

## Build (deterministic)
From a VS 2022 x64 Native Tools prompt:
```
cl /EHsc /W4 /Fe:authorized_win64_calculator.exe authorized_win64_calculator.cpp advapi32.lib
```

## Run / expected output
```
authorized_win64_calculator.exe
...
LaunchConfirmation=Calculator.exe PID=<n> ExitCode=<n>
```
`<n>` values are the only per-run external values (assigned by the OS).

## Register capture
See `capture_regs.windbg` and the labeled fixture
`register_snapshot_fixture.txt` (RAX RBX RCX RDX RSI RDI RSP RBP RIP
at the breakpoint after CreateProcessW succeeds).

## Validation
See `validator_fixture.txt` for the launch-proof checks (console
invariant, tasklist/Get-Process cross-check, parent/child linkage).
