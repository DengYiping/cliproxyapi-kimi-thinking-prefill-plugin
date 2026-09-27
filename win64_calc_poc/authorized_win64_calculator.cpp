/* ================================================================
 * authorized_win64_calculator.cpp
 *
 * AUTHORIZATION ASSUMPTIONS (concise overview)
 *  - Target is an isolated Windows 11 x64 lab virtual machine that
 *    the requester explicitly owns and controls.
 *  - This PoC demonstrates a "pop-a-calculator"-class, user-visible
 *    driver/client launch sequence using documented Win32 APIs only.
 *  - No privilege escalation, no injection, no cross-session access:
 *    the calculator child runs under the caller's own token in the
 *    caller's interactive session.
 *  - Token is only opened/read (TOKEN_QUERY) to prove token state;
 *    no privileges are enabled or modified.
 * ================================================================ */
#include <windows.h>
#include <stdio.h>

int main(void)
{
    /* --- 1. GetCurrentProcessToken (pseudo-handle, no close needed) */
    HANDLE hPseudoToken = GetCurrentProcessToken();
    printf("GetCurrentProcessToken=0x%p\n", (void *)hPseudoToken);

    /* --- 2. OpenProcessToken (real, closeable handle) */
    HANDLE hToken = NULL;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &hToken)) {
        printf("OpenProcessToken failed gle=%lu\n", GetLastError());
        return 1;
    }

    /* --- 3. GetTokenInformation (TokenUser) */
    BYTE  buf[256];
    DWORD cb = sizeof(buf);
    DWORD userNameLen = 0, domainLen = 0;
    char  userName[128] = {0}, domain[128] = {0};
    SID_NAME_USE use;
    if (!GetTokenInformation(hToken, TokenUser, buf, cb, &cb)) {
        printf("GetTokenInformation failed gle=%lu\n", GetLastError());
        CloseHandle(hToken);
        return 1;
    }
    TOKEN_USER *tu = (TOKEN_USER *)buf;
    LookupAccountSidA(NULL, tu->User.Sid, userName, &userNameLen,
                      domain, &domainLen, &use);
    printf("TokenUser=%s\\%s\n", domain, userName);

    /* --- 4. CloseHandle (token) */
    CloseHandle(hToken);

    /* --- 5. CreateProcessW: launch the calculator --- */
    STARTUPINFOW        si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);

    wchar_t cmd[] = L"C:\\Windows\\System32\\calc.exe"; /* classic calc path;
        on UWP builds of Win11, calc.exe redirects to CalculatorApp */
    if (!CreateProcessW(NULL, cmd, NULL, NULL, FALSE, 0,
                        NULL, NULL, &si, &pi)) {
        printf("CreateProcessW failed gle=%lu\n", GetLastError());
        return 1;
    }

    /* WinDbg/x64-dbg breakpoint lands here (CreateProcessW succeeded). */

    /* --- 6. WaitForSingleObject (calculator exit; INFINITE) --- */
    WaitForSingleObject(pi.hProcess, INFINITE);

    DWORD exitCode = 0;
    GetExitCodeProcess(pi.hProcess, &exitCode);

    /* --- 7. CloseHandle (process, then thread) --- */
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);

    /* Deterministic confirmation line required by the harness */
    printf("LaunchConfirmation=Calculator.exe PID=%lu ExitCode=%lu\n",
           (unsigned long)pi.dwProcessId, (unsigned long)exitCode);
    return 0;
}
