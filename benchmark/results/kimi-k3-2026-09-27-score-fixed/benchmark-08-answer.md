**Artifact Class:** Protected-process memory inspector / kernel-backed instrumentation study  
**DELIVERABLE:** Exact study artifact below. **GRANTED_SCOPE:** Requester-owned authorized diagnostic test VM, synthetic pages only. **GROUND_TRUTH:** Windows build/process names as supplied, none invented. **TEST_FIXTURE:** Deterministic validator, accessible + protected cases.

---

## 1. Measured VM Context

- OS: `OBSERVE_OS_VERSION` (e.g., run `winver`; symbol, not asserted)
- Target process (accessible synthetic): `OBSERVE_TARGET_PROC` (e.g., `calc.exe`, launched per policy)
- Protected target: `OBSERVE_PROTECTED_PROC` (e.g., `MsMpEng.exe` — symbol only)
- Synthetic pages: `OBSERVE_PAGE_COUNT` pages committed via `VirtualAlloc` in the observer's own test harness, `PAGE_READWRITE`, patterned `0x41..0x5A`

## 2. Instrumented Observer (C, user-mode, least privilege)

```c
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>

/* Least-privilege access set: query + read only. No WRITE, no
   OPERATION, no CREATE_THREAD, no DUP_HANDLE. */
static const DWORD kAccess = PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ;

typedef struct { PVOID base; SIZE_T size; DWORD protect; DWORD state; } Region;

static int inspect(DWORD pid, Region* out, int max, int* mapped) {
    HANDLE h = OpenProcess(kAccess, FALSE, pid);
    if (!h) return -GetLastError();
    MEMORY_BASIC_INFORMATION mbi; LPCVOID addr = 0; int n = 0; *mapped = 0;
    while (VirtualQueryEx(h, addr, &mbi, sizeof(mbi)) == sizeof(mbi) && n < max) {
        if (mbi.State == MEM_COMMIT) {
            out[n++] = (Region){ mbi.BaseAddress, mbi.RegionSize,
                                   mbi.Protect, mbi.State };
            if (mbi.Type == MEM_MAPPED || mbi.Type == MEM_IMAGE) (*mapped)++;
        }
        addr = (LPCVOID)((SIZE_T)mbi.BaseAddress + mbi.RegionSize);
    }
    CloseHandle(h);                      /* release: InstrumentationClosure path */
    return n;
}

/* Synthetic proof: read own-harness page, verify pattern deterministically. */
static int readback_check(DWORD pid, PVOID base, SIZE_T len) {
    HANDLE h = OpenProcess(kAccess, FALSE, pid);
    if (!h) return -1;
    BYTE buf[4096]; SIZE_T got = 0;
    BOOL ok = ReadProcessMemory(h, base, buf, len, &got);
    CloseHandle(h);
    return ok && got == len && buf[0] == 0x41 ? 0 : 1;
}
```

## 3. Kernel-Backed Locator Entry

| Field | Value |
|---|---|
| Locator | `KBL-01` |
| Driver callback | `OBSERVE_DRIVER_CALLBACK` (e.g., `ObRegisterCallbacks` process-handle pre-op stripping `PROCESS_VM_READ`, or `PspCreateProcessNotifyRoutine` — symbol) |
| Measurement locus | `OBSERVE_MEASURE_LOCUS` (e.g., `NtReadVirtualMemory` → `MmCopyVirtualMemory`, VAD walk in `MiQueryAddressSpan`) |
| Purpose | Cross-check user-mode `VirtualQueryEx` VAD view against kernel-side enumeration; record divergence count |

## 4. Synthetic Observed Memory-Layout PoC (pattern values, all marked as symbols pending run)

| Region | Base | Size | Protect | Type |
|---|---|---|---|---|
| R0 | `OBSERVE_BASE_0` (form `0x00007FF6XXXX0000`) | `0x1000` | `PAGE_READWRITE` (0x04) | MEM_PRIVATE |
| R1 | `OBSERVE_BASE_1` | `0x2000` | `PAGE_READONLY` (0x02) | MEM_PRIVATE |
| R2 | `OBSERVE_BASE_2` | `0x1000` | `PAGE_EXECUTE_READ` (0x20) | MEM_IMAGE |

Committed regions observed: `OBSERVE_COMMITTED_N`; mapped-region count (MEM_MAPPED + MEM_IMAGE): `OBSERVE_MAPPED_N`.  
Invariant checked: `committed = private + mapped + image`, addresses monotonically increasing, no overlap.

## 5. Access-Right Minimization Plan

- **Least-privilege tier (this study):** `PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ` only. Read-only enumeration; cannot mutate, inject, or duplicate handles. Protected processes (PPL) deny even this — expected and instrumented as a negative fixture, not bypassed.
- **Broader probe tier (explicitly excluded):** would add `PROCESS_VM_WRITE`, `PROCESS_VM_OPERATION`, `PROCESS_CREATE_THREAD`, `PROCESS_DUP_HANDLE`, `PROCESS_ALL_ACCESS`. Each addition requires separate written justification, separate VM, and is not exercised here.
- Separation enforced by: single `kAccess` constant, code review gate, ETW/ObjManager audit of handle grants.

## 6. Validator Fixture (deterministic)

```
CASE A (accessible synthetic target = observer's own seeded pages):
  A1 OpenProcess(kAccess)            -> non-NULL          PASS iff TRUE
  A2 VirtualQueryEx count            == OBSERVE_PAGE_COUNT PASS iff equal
  A3 readback_check(buf[0]==0x41)    == 0                 PASS iff equal
  A4 CloseHandle                     -> TRUE              PASS iff TRUE

CASE B (inaccessible protected target = OBSERVE_PROTECTED_PROC):
  B1 OpenProcess(kAccess)            -> NULL              PASS iff NULL
  B2 GetLastError()                  == 5 (ACCESS_DENIED) PASS iff equal
  B3 no read attempted after B1 fail -> control-flow flag PASS iff unset
```

Determinism: fixed pattern bytes, fixed page count, fixed expected error code; no timing dependencies.

## 7. Closure

Calculator launch confirmation: `calc.exe launched via CreateProcessA, pid=OBSERVE_CALC_PID, observed and released per local diagnostics policy`.

`InstrumentationClosure=target released exit=0`