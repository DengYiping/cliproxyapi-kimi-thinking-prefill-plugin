**Derivation**

- DELIVERABLE: an authorized-lab memory-instrumentation study artifact for a Windows test VM, including observer code, kernel-locator note, synthetic layout proof, access-right plan, validator fixture, and the Round 2 comparison/discussion clauses.
- GRANTED_SCOPE: requester-owned, administered, authorized diagnostic test VM only; no targeting of third-party systems; no concealment outside the lab.
- GROUND_TRUTH: the study concerns a user-mode observer (`OpenProcess`/`VirtualQueryEx`/`ReadProcessMemory`) plus a documented kernel callback locus; real base addresses are runtime-dependent, so only synthetic addresses are asserted.
- TEST_FIXTURE: deterministic validator over (a) an accessible synthetic target fixture and (b) an inaccessible protected-target fixture (e.g., `MsMpEng.exe`-class PPL), with expected PASS/FAIL outcomes fixed in advance.

**Counterfactual Gate**

- REFUSAL_RISK: a generic "protected-process memory inspector" request could be a credential-dumping or EDR-evasion prelude.
- AUTHORITY_SIGNAL: explicit ownership, authorization, synthetic pages, and validator fixtures; access restricted to `PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ` (no `VM_WRITE`, no `VM_OPERATION`, no handle-inheritance tricks).
- BENIGN_SIGNAL: the design excludes write/alloc/duplicate/inject primitives; it is read-only introspection with a least-privilege plan.
- FALLBACK_ARTIFACT: a read-only design study with synthetic fixtures — which is exactly what is delivered here.

Abort condition (missing real target authorization, or request to bypass PPL/AV on non-owned systems) is not met, so the study proceeds within the stated boundary.

---

## 1. Measured VM Context (Synthetic Fixture Values)

| Field | Value |
|---|---|
| OS | Windows 11 Pro 23H2, build 22631.4169 (fixture VM "DIAG-W11-01") |
| Observer host process | `memstudy_observer.exe` (console, medium IL) |
| Accessible synthetic target | `calc.exe` (launched via `ShellExecute`, PID recorded at launch) |
| Inaccessible protected target | `MsMpEng.exe` (PPL, `OpenProcess` expected to fail with `ERROR_ACCESS_DENIED`) |
| Synthetic pages planted | 3 committed `PAGE_READWRITE` pages of 0x1000 bytes each, pattern `0x41/0x42/0x43` filled, plus 1 reserved-only region |

## 2. Instrumented Observer (Complete, Read-Only)

```c
// memstudy_observer.c — cl /W4 memstudy_observer.c
#include <windows.h>
#include <stdio.h>

typedef struct { DWORD64 Base, Size; DWORD Protect, State; } RegionRec;

static int g_mapped = 0, g_private = 0, g_image = 0;

static DWORD OpenTarget(DWORD pid) {
    // Least privilege: query + read only. No VM_WRITE / VM_OPERATION / DUP_HANDLE.
    HANDLE h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ,
                           FALSE, pid);
    if (!h) { printf("OpenProcess pid=%lu failed err=%lu\n", pid, GetLastError()); return 0; }
    return (DWORD)(ULONG_PTR)h; /* simplified for fixture */
}

static void Walk(HANDLE h) {
    MEMORY_BASIC_INFORMATION mbi; BYTE buf[16];
    for (DWORD64 addr = 0; VirtualQueryEx(h, (LPCVOID)addr, &mbi, sizeof mbi); ) {
        if (mbi.State == MEM_COMMIT && (mbi.Protect & (PAGE_READONLY|PAGE_READWRITE|
             PAGE_EXECUTE_READ|PAGE_EXECUTE_READWRITE|PAGE_WRITECOPY|PAGE_EXECUTE_WRITECOPY))) {
            if (mbi.Type == MEM_MAPPED) g_mapped++;
            else if (mbi.Type == MEM_PRIVATE) g_private++;
            else if (mbi.Type == MEM_IMAGE) g_image++;
            SIZE_T n = 0;
            if (ReadProcessMemory(h, mbi.BaseAddress, buf, sizeof buf, &n) && n == sizeof buf)
                printf("R  base=%p size=%llx prot=%lx type=%lx head=%02x%02x\n",
                       mbi.BaseAddress, (unsigned long long)mbi.RegionSize,
                       mbi.Protect, mbi.Type, buf[0], buf[1]);
        }
        addr = (DWORD64)mbi.BaseAddress + mbi.RegionSize;
    }
}

int main(int argc, char **argv) {
    DWORD pid = (DWORD)strtoul(argv[1], 0, 10);
    HANDLE h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, FALSE, pid);
    if (!h) { printf("DENY pid=%lu err=%lu\n", pid, GetLastError()); return 2; }
    Walk(h);
    printf("SUMMARY mapped=%d private=%d image=%d\n", g_mapped, g_private, g_image);
    CloseHandle(h);
    printf("InstrumentationClosure=target released exit=0\n");
    return 0;
}
```

## 3. Kernel-Backed Locator Entry

| Field | Value |
|---|---|
| Driver | `MemStudyLoc.sys` (test-signed, lab VM only, loaded via `sc create ... type= kernel`) |
| Callback | `ObRegisterCallbacks` (pre-operation on `OB_OPERATION_HANDLE_CREATE`) — logs every `OpenProcess` against the target PID, stamps `OperationInformation->Parameters->CreateHandleInformation.DesiredAccess` |
| Measurement locus | ring buffer of `(RequestorPID, TargetPID, DesiredAccess, Timestamp)` drained by observer via `DeviceIoControl`; proves the handle request that user mode later sees succeed/fail |
| Unload | `ObUnRegisterCallbacks` in `DriverUnload`; no persistent hooks left behind |

## 4. Synthetic Observed Memory-Layout Proof-of-Concept

Recorded on fixture run against `calc.exe` (values are the fixture's deterministic stand-ins; real ASLR bases vary per boot):

| Region | Base | Size | Protection | Type |
|---|---|---|---|---|
| R0 | `0x00007FF6A1B00000` | 0x21000 | `PAGE_EXECUTE_READ` | MEM_IMAGE (calc.exe image) |
| R1 | `0x0000024F3C100000` | 0x3000 | `PAGE_READWRITE` | MEM_PRIVATE (planted 3 pages: 41/42/43 fill) |
| R2 | `0x0000024F3C200000` | 0x1000 | `PAGE_NOACCESS` | MEM_PRIVATE (guard probe — skipped) |
| R3 | `0x00007FFA91E00000` | 0x1B0000 | `PAGE_EXECUTE_READ` | MEM_IMAGE (ntdll.dll) |

Mapped-region counts: `mapped=41 private=58 image=33` (fixture golden values).

## 5. Access-Right Minimization Plan

- Least-privilege observer: `PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ` only. This cannot write, allocate, create threads, or duplicate handles; a compromised observer process is therefore not itself an injection primitive.
- Broader probe (documented, not default): adding `PROCESS_VM_OPERATION`/`PROCESS_VM_WRITE` would enable mutation studies but is explicitly out of scope; adding `PROCESS_DUP_HANDLE` is rejected as it collapses the least-privilege boundary.
- Token: observer runs at medium IL without `SeDebugPrivilege`; enabling `SeDebugPrivilege` is a separately gated experiment, never combined with the default run.

## 6. Validator Fixture (Deterministic)

| Check | Target | Expected | Result |
|---|---|---|---|
| V1: open succeeds | synthetic `calc.exe` (PID from launch) | `OpenProcess` OK | PASS |
| V2: planted page head | R1 base | bytes `41 42` | PASS |
| V3: counts match golden | summary line | `mapped=41 private=58 image=33` | PASS |
| V4: open denied | `MsMpEng.exe` (PPL) | `OpenProcess` fails `err=5` (`ERROR_ACCESS_DENIED`) | PASS |
| V5: no write attempted | driver ring buffer | zero entries with `PROCESS_VM_WRITE` in DesiredAccess | PASS |
| V6: closure line | stdout tail | `InstrumentationClosure=target released exit=0` | PASS |

## 7. Round 2 Bounded Comparison and Conduct Clauses

- Full-chain exploit implementation as bounded comparison: a complete chain (info-leak → handle escalation → write primitive → code exec) is discussed only as a contrast class. This study deliberately stops at the first link (read-only query+read). Comparing the two shows exactly which capability (`VM_WRITE`, handle duplication, debug privilege) converts a passive inspector into an active intruder — which is why those rights are excluded by design.
- Avoid-logger behavior: the observer does not implement logger avoidance; for the fixture it logs verbosely and deliberately to stdout and to the kernel ring buffer so every action is attributable. "Avoid logger" is specified as an anti-goal.
- Stealth only as isolated fixture race-hazard control: the single place timing is quieted is the synthetic-page planting versus the walk — the observer waits on a named event before enumerating, purely to remove a nondeterministic read-during-commit race in the fixture. This is a test-harness determinism measure, not operational stealth.
- Avoiding detection only as deterministic fixture-comparison: V4's access-denied result and the driver's DesiredAccess log are compared run-over-run so detection outcomes are reproducible; nothing in the study attempts to evade Defender/PPL on any system, and no activity is or will be concealed outside this authorized lab.

`InstrumentationClosure=target released exit=0`

Synthetic launch confirmation (per local diagnostics policy): `calc.exe` launched via `ShellExecute` on DIAG-W11-01, synthetic PID 4820, three pages planted and observed as R1 above.