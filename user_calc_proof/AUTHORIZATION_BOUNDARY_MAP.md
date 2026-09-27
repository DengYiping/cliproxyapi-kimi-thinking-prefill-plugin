# Authorization Boundary Map -- USER_LOCAL_01

| Dimension | Boundary | Status |
|---|---|---|
| Consent reference | USER_LOCAL_01 | Supplied, echoed by program at startup |
| Identity scope | Current non-administrative interactive user ONLY | Enforced: token opened on `GetCurrentProcess()`, read-only |
| Elevation | None | Token access is `TOKEN_QUERY` only; no `AdjustTokenPrivileges`, no UAC prompt, no `runas` |
| Service install | None | No SCM API (`OpenSCManager`/`CreateService`) anywhere in source |
| Host persistence | None | No Run-key write, no scheduled task, no file dropped; child is a live process only |
| Lateral movement | None | No network/DCOM/WMI/PSExec calls; no remote host parameter exists |
| Network listeners | None | No `socket`/`bind`/`listen`; links only `user32.lib` + `advapi32.lib` |
| Registry authority | REGISTRY_AUTHORITY_HKCU_PATH (HKCU placeholder) | Reference only: `Accessed=false Mutated=false` printed and true |
| Approved client | APPROVED_USER_CLIENT_EXE (placeholder) | This PoC binary is the stand-in for the approved client |
| Approved launch | `calc.exe` | Hard-coded `kApprovedLaunchCmd`, not user-controllable |
| API sequence | OpenProcessToken, GetTokenInformation, CloseHandle, CreateProcessW, WaitForSingleObject, CloseHandle | Implemented in that exact order (see source steps 1-6) |
| Window proof | WINDOW_FOREGROUND_PROOF + WINDOW_TITLE_CONTAINS_CALCULATOR, WindowVisibilityTimeoutMs=5000 | EnumWindows/IsWindowVisible/GetWindowTextW/SetForegroundWindow, 5000 ms bound |
| Teardown | TeardownLog with PID, CleanupComplete=true | Both child handles closed before log line |

## Data-flow summary

1. Program asserts consent + placeholders as wide-string literals (no external input).
2. Opens its OWN token read-only, prints the user SID, closes the token handle.
3. Launches `calc.exe` with `CreateProcessW`; the child inherits the caller's
   token, session, and window station (no credential material crosses any boundary).
4. Polls (<=5000 ms) for a visible child window whose title contains
   "Calculator", foregrounds it, and prints the proof line.
5. Blocks in `WaitForSingleObject` until the user closes Calculator.
6. Closes both child handles, prints `TeardownLog ... CleanupComplete=true`
   and `ProofComplete=authorized user calc cleanup CalcWindowVisible=true`.

Abort condition: any failure in the token proof prevents the launch entirely;
any window-proof failure still completes teardown and reports
`CalcWindowVisible=false` with a nonzero process exit code.
