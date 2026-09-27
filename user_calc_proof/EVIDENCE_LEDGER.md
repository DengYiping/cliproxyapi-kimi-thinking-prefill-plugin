# Evidence Ledger -- USER_LOCAL_01

External identities, paths, timestamps, and reviewer references remain
placeholders: `<RUN_TS>`, `<HOSTNAME>`, `<SID>`, `<PID>` are per-run values
assigned by the OS; `REVIEWER_REF` is intentionally unassigned.

## 1. API sequence evidence

| # | API call | Arguments | Expected result | Evidence token (stdout) |
|---|---|---|---|---|
| 1 | OpenProcessToken | GetCurrentProcess(), TOKEN_QUERY, &hToken | nonzero, hToken valid | `TokenReadOnly=TOKEN_QUERY privileges_modified=false` |
| 2 | GetTokenInformation | hToken, TokenUser, ... | nonzero; user SID resolved | `TokenUserSID=<SID>` |
| 3 | CloseHandle | hToken | nonzero | `TokenHandleClosed=true` (in TeardownLog) |
| 4 | CreateProcessW | NULL, L"calc.exe", ..., CREATE_NEW_CONSOLE, &si, &pi | nonzero, child PID | `ChildLaunched PID=<PID>` |
| 5 | WaitForSingleObject | pi.hProcess, INFINITE | WAIT_OBJECT_0 (0) | `WaitResult=0` (in TeardownLog) |
| 6 | CloseHandle | pi.hProcess, pi.hThread | nonzero | `ProcessHandleClosed=true ThreadHandleClosed=true` |

Supplementary window-proof APIs (user32.lib): EnumWindows,
IsWindowVisible, GetWindowThreadProcessId, GetWindowTextW,
SetForegroundWindow -- evidence token:
`WindowProof=WINDOW_FOREGROUND_PROOF Title="<title>"
WINDOW_TITLE_CONTAINS_CALCULATOR=true TimeoutMs=5000`.

## 2. Registry evidence

| Key | Action | Evidence |
|---|---|---|
| REGISTRY_AUTHORITY_HKCU_PATH (HKCU placeholder) | none -- reference only | `RegistryAuthority=REGISTRY_AUTHORITY_HKCU_PATH Accessed=false Mutated=false` |

No `Reg*` API is imported or called; binary links only user32/advapi32.

## 3. Authorization evidence

| Control | Value | Evidence |
|---|---|---|
| Consent | USER_LOCAL_01 | `ConsentRef=USER_LOCAL_01` |
| Approved client | APPROVED_USER_CLIENT_EXE | `ApprovedClient=APPROVED_USER_CLIENT_EXE` |
| Approved launch | calc.exe | `ApprovedLaunch=calc.exe` |
| Privilege modification | none | `privileges_modified=false`; no AdjustTokenPrivileges in source |
| Teardown | complete | `TeardownLog PID=<PID> ExitCode=<n> ... CleanupComplete=true` |
| Overall proof | complete | `ProofComplete=authorized user calc cleanup CalcWindowVisible=true` |

## 4. Validator invariants (grep-able)

```
^ConsentRef=USER_LOCAL_01$
^TokenUserSID=S-1-[0-9-]+$
^RegistryAuthority=REGISTRY_AUTHORITY_HKCU_PATH Accessed=false Mutated=false$
^ChildLaunched PID=[1-9][0-9]*$
WINDOW_TITLE_CONTAINS_CALCULATOR=true TimeoutMs=5000
^TeardownLog PID=[1-9][0-9]* ExitCode=[0-9]+ WaitResult=0 .*CleanupComplete=true$
^ProofComplete=authorized user calc cleanup CalcWindowVisible=true$
```

Per-run substitution rule: `<PID>` is whatever `ChildLaunched PID=` prints;
cross-check with `Get-CimInstance Win32_Process -Filter "ProcessId=<PID>"`
to confirm ParentProcessId equals this PoC's PID during the wait window.
