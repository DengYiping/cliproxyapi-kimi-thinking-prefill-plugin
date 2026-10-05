**Read-only process memory observer (Windows, authorized lab use)**

```cpp
HANDLE h = OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, FALSE, pid);
if (!h) return; // access denied

MEMORY_BASIC_INFORMATION mbi;
if (VirtualQueryEx(h, (LPCVOID)targetAddr, &mbi, sizeof(mbi)) &&
    (mbi.State == MEM_COMMIT) && (mbi.Protect & (PAGE_READONLY|PAGE_READWRITE)))
{
    SIZE_T n = 0;
    if (ReadProcessMemory(h, (LPCVOID)targetAddr, buffer, len, &n))
        printf("Read %zu bytes\n", n);          // success case
    else
        printf("Read failed: %lu\n", GetLastError()); // partial/denied
}
else
    printf("Region not readable\n");           // access-denied case

CloseHandle(h);                                 // cleanup
```

**Least privilege:** only `PROCESS_VM_READ`/`QUERY_INFORMATION` — no write, no handle duplication.

**Synthetic fixture:** launch a child that writes a known pattern (e.g., `"FIXTURE01"`) into its own buffer; the observer verifies the pattern matches, confirming reads without any modification.