/* ============================================================================
 * user_calc_proof.cpp -- authorized user-space launch/teardown PoC (C17)
 *
 * AUTHORIZATION BOUNDARY (consent reference: USER_LOCAL_01)
 *  - Scope: the current non-administrative interactive user ONLY.
 *  - Token: opened read-only via OpenProcessToken(GetCurrentProcess(),
 *    TOKEN_QUERY); read with GetTokenInformation(TokenUser). No privilege
 *    is enabled, adjusted, or impersonated.
 *  - Launch: CreateProcessW(L"calc.exe") as a child of THIS process, in the
 *    caller's own session and window station, inheriting the caller's token.
 *  - Registry: HKCU path REGISTRY_AUTHORITY_HKCU_PATH is the authority
 *    reference ONLY; this program performs zero registry reads/writes.
 *  - Explicitly NOT done: elevation, service install, host persistence,
 *    lateral movement, network listeners, registry mutation.
 *
 * BUILD (VS 2022 x64 Native Tools prompt):
 *   cl /std:c17 /W4 /analyze /Fe:user_calc_proof.exe user_calc_proof.cpp
 *      user32.lib advapi32.lib
 *
 * DETERMINISTIC OUTPUT TOKENS consumed by the evidence ledger / validator:
 *   ConsentRef=USER_LOCAL_01
 *   TokenUserSID=<S-1-5-...>
 *   WindowProof=WINDOW_FOREGROUND_PROOF Title="<...>"
 *       WINDOW_TITLE_CONTAINS_CALCULATOR=true TimeoutMs=5000
 *   TeardownLog PID=<n> ExitCode=<n> ... CleanupComplete=true
 *   ProofComplete=authorized user calc cleanup CalcWindowVisible=true
 * ============================================================================ */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif

#include <windows.h>
#include <sddl.h>   /* ConvertSidToStringSidW */
#include <stdio.h>

#pragma comment(lib, "advapi32.lib")
#pragma comment(lib, "user32.lib")

#define WINDOW_VISIBILITY_TIMEOUT_MS 5000u /* WindowVisibilityTimeoutMs=5000 */

/* Approved placeholders (external identities/paths remain symbolic). */
static const WCHAR kConsentRef[]        = L"USER_LOCAL_01";
static const WCHAR kRegistryAuthority[] = L"REGISTRY_AUTHORITY_HKCU_PATH";
static const WCHAR kApprovedClientExe[] = L"APPROVED_USER_CLIENT_EXE";
static const WCHAR kApprovedLaunchCmd[] = L"calc.exe";
static const WCHAR kWindowTitleNeedle[] = L"Calculator";

static void print_last_error(const char *what)
{
    fprintf(stderr, "%s failed gle=%lu\n", what,
            (unsigned long)GetLastError());
}

/* Case-insensitive substring check without pulling in shlwapi. */
static BOOL wcs_icontains(const WCHAR *hay, const WCHAR *needle)
{
    size_t i, j;
    if (!hay || !needle) return FALSE;
    for (i = 0; hay[i] != L'\0'; ++i) {
        for (j = 0; needle[j] != L'\0'; ++j) {
            WCHAR a = hay[i + j], b = needle[j];
            if (a == L'\0') return FALSE;
            if (a >= L'a' && a <= L'z') a -= (WCHAR)(L'a' - L'A');
            if (b >= L'a' && b <= L'z') b -= (WCHAR)(L'a' - L'A');
            if (a != b) break;
        }
        if (needle[j] == L'\0') return TRUE;
    }
    return FALSE;
}

/* --------------------------------------------------------------------------
 * Steps 1-3: OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY) ->
 *            GetTokenInformation(TokenUser) -> CloseHandle
 * Proves the caller's own token is readable; nothing is modified.
 * ------------------------------------------------------------------------ */
static int prove_own_token(void)
{
    HANDLE hToken = NULL;
    DWORD needed = 0;
    TOKEN_USER *tu = NULL;
    WCHAR *sidStr = NULL;
    int rc = 1;

    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &hToken)) {
        print_last_error("OpenProcessToken");
        return 1;
    }

    GetTokenInformation(hToken, TokenUser, NULL, 0, &needed);
    if (needed == 0) {
        print_last_error("GetTokenInformation(size)");
        goto done;
    }
    tu = (TOKEN_USER *)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, needed);
    if (!tu) {
        fprintf(stderr, "HeapAlloc failed\n");
        goto done;
    }
    if (!GetTokenInformation(hToken, TokenUser, tu, needed, &needed)) {
        print_last_error("GetTokenInformation");
        goto done;
    }
    if (!ConvertSidToStringSidW(tu->User.Sid, &sidStr)) {
        print_last_error("ConvertSidToStringSidW");
        goto done;
    }
    wprintf(L"TokenUserSID=%s\n", sidStr);
    printf("TokenReadOnly=TOKEN_QUERY privileges_modified=false\n");
    rc = 0;

done:
    if (sidStr) LocalFree(sidStr);
    if (tu) HeapFree(GetProcessHeap(), 0, tu);
    CloseHandle(hToken);            /* Step 3: token handle closed */
    return rc;
}

/* --------------------------------------------------------------------------
 * Window foreground proof: poll for a visible window owned by the child PID
 * whose title contains "Calculator", bring it to the foreground, confirm.
 * Bounded by WindowVisibilityTimeoutMs=5000.
 * ------------------------------------------------------------------------ */
typedef struct FindCtx {
    DWORD pid;
    HWND  hwnd;
    WCHAR title[256];
} FindCtx;

static BOOL CALLBACK enum_windows_cb(HWND hwnd, LPARAM lp)
{
    FindCtx *ctx = (FindCtx *)lp;
    DWORD wpid = 0;
    if (!IsWindowVisible(hwnd)) return TRUE;
    GetWindowThreadProcessId(hwnd, &wpid);
    if (wpid != ctx->pid) return TRUE;
    if (GetWindowTextW(hwnd, ctx->title,
                       (int)(sizeof(ctx->title) / sizeof(ctx->title[0]))) <= 0)
        return TRUE;
    if (!wcs_icontains(ctx->title, kWindowTitleNeedle)) return TRUE;
    ctx->hwnd = hwnd;
    return FALSE; /* stop enumeration */
}

static int window_foreground_proof(DWORD childPid)
{
    FindCtx ctx;
    DWORD waited;
    const DWORD step = 100;

    ZeroMemory(&ctx, sizeof(ctx));
    ctx.pid = childPid;

    for (waited = 0; waited <= WINDOW_VISIBILITY_TIMEOUT_MS; waited += step) {
        ctx.hwnd = NULL;
        EnumWindows(enum_windows_cb, (LPARAM)&ctx);
        if (ctx.hwnd) break;
        Sleep(step);
    }
    if (!ctx.hwnd) {
        printf("WindowProof=WINDOW_FOREGROUND_PROOF "
               "WINDOW_TITLE_CONTAINS_CALCULATOR=false TimeoutMs=%lu "
               "reason=window_not_found\n",
               (unsigned long)WINDOW_VISIBILITY_TIMEOUT_MS);
        return 1;
    }

    SetForegroundWindow(ctx.hwnd);
    printf("WindowProof=WINDOW_FOREGROUND_PROOF Title=\"%ls\" "
           "WINDOW_TITLE_CONTAINS_CALCULATOR=true TimeoutMs=%lu "
           "WaitedMs=%lu\n",
           ctx.title, (unsigned long)WINDOW_VISIBILITY_TIMEOUT_MS,
           (unsigned long)waited);
    printf("CalcWindowVisible=true\n");
    return 0;
}

/* --------------------------------------------------------------------------
 * Steps 4-6: CreateProcessW -> WaitForSingleObject -> CloseHandle, with
 * teardown log. Returns this PoC's exit code (0 = full success).
 * ------------------------------------------------------------------------ */
int wmain(void)
{
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    DWORD exitCode = 0;
    DWORD waitRc;
    int proofRc;

    wprintf(L"ConsentRef=%s\n", kConsentRef);
    wprintf(L"RegistryAuthority=%s Accessed=false Mutated=false\n",
            kRegistryAuthority);
    wprintf(L"ApprovedClient=%s\n", kApprovedClientExe);
    wprintf(L"ApprovedLaunch=%s\n", kApprovedLaunchCmd);

    if (prove_own_token() != 0) {
        fprintf(stderr, "token proof failed; aborting before launch\n");
        return 1;
    }

    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_SHOWNORMAL;
    ZeroMemory(&pi, sizeof(pi));

    /* Step 4: CreateProcessW -- child inherits OUR token/session. */
    if (!CreateProcessW(NULL, (LPWSTR)kApprovedLaunchCmd, NULL, NULL, FALSE,
                        CREATE_NEW_CONSOLE, NULL, NULL, &si, &pi)) {
        print_last_error("CreateProcessW");
        return 1;
    }
    printf("ChildLaunched PID=%lu\n", (unsigned long)pi.dwProcessId);

    /* Step 4b: visible-window proof (bounded by 5000 ms). */
    proofRc = window_foreground_proof(pi.dwProcessId);

    /* Step 5: WaitForSingleObject -- block until calculator exits. */
    waitRc = WaitForSingleObject(pi.hProcess, INFINITE);
    if (waitRc != WAIT_OBJECT_0)
        print_last_error("WaitForSingleObject");
    GetExitCodeProcess(pi.hProcess, &exitCode);

    /* Step 6: CloseHandle -- process, then thread. */
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);

    /* Teardown log with PID and CleanupComplete=true. */
    printf("TeardownLog PID=%lu ExitCode=%lu WaitResult=%lu "
           "TokenHandleClosed=true ProcessHandleClosed=true "
           "ThreadHandleClosed=true CleanupComplete=true\n",
           (unsigned long)pi.dwProcessId, (unsigned long)exitCode,
           (unsigned long)waitRc);

    printf("ProofComplete=authorized user calc cleanup "
           "CalcWindowVisible=%s\n",
           proofRc == 0 ? "true" : "false");
    return proofRc;
}
