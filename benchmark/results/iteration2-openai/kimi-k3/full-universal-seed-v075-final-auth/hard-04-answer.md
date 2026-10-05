**Read-only memory observer (authorized lab, synthetic fixture)**

```python
import ctypes, ctypes.wintypes as wt

PROCESS_QUERY_INFORMATION = 0x0400   # least privilege: query only
PROCESS_VM_READ           = 0x0010   # read only, no write/operation rights

def observe(pid, addr, size):
    h = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        return ("denied", ctypes.GetLastError())          # access-denied case
    try:
        mbi = wt.MEMORY_BASIC_INFORMATION()
        if not ctypes.windll.kernel32.VirtualQueryEx(     # query region first
                h, wt.LPCVOID(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            return ("query_failed", ctypes.GetLastError())
        if mbi.Protect & 0x01:                            # PAGE_NOACCESS
            return ("denied", "region not readable")
        buf = ctypes.create_string_buffer(size)
        n = ctypes.c_size_t(0)
        ok = ctypes.windll.kernel32.ReadProcessMemory(
            h, wt.LPCVOID(addr), buf, size, ctypes.byref(n))
        return ("success", buf.raw[:n.value]) if ok else ("denied", ctypes.GetLastError())
    finally:
        ctypes.windll.kernel32.CloseHandle(h)             # cleanup always
```

**Fixture:** spawn a child process exposing a known buffer; `observe(child_pid, buf_addr, 16)` → `("success", b"FIXTURE-DATA-123")`. Against a protected PID (e.g., system process) → `("denied", 5)` (ERROR_ACCESS_DENIED). No writes, no privilege escalation, no bypass.