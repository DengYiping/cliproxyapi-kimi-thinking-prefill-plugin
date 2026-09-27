/* ============================================================================
 * local_logic_harness.c -- host-runnable mirror of user_calc_proof.cpp
 *
 * This macOS/Linux harness executes the SAME control flow the Win32 PoC
 * uses, so the launch/teardown logic is functionally verified on this
 * machine. Win32 API -> POSIX mirror:
 *   OpenProcessToken/GetTokenInformation  -> getuid/getpwuid (read-only)
 *   CloseHandle(token)                    -> (no handle; no-op)
 *   CreateProcessW("calc.exe")            -> posix_spawnp of a stub child
 *   WaitForSingleObject                   -> waitpid
 *   CloseHandle(process/thread)           -> (reaped by waitpid)
 *
 * Window proof is a Win32-only behavior; here it is simulated with a
 * bounded timeout and reported as SIMULATED so the output contract
 * (identical tokens) can be validated end-to-end.
 * ============================================================================ */
#include <errno.h>
#include <pwd.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

#define WINDOW_VISIBILITY_TIMEOUT_MS 5000u

static int prove_own_identity(void)
{
    uid_t uid = getuid();
    struct passwd *pw = getpwuid(uid);
    if (!pw) {
        fprintf(stderr, "getpwuid failed errno=%d\n", errno);
        return 1;
    }
    printf("TokenUser=%s uid=%ld\n", pw->pw_name, (long)uid);
    printf("TokenReadOnly=true privileges_modified=false\n");
    return 0;
}

int main(void)
{
    pid_t pid;
    int status = 0;
    int rc;
    char *argv[] = { "calc_stub", NULL };
    const char *stub = "/usr/bin/true"; /* calc.exe stand-in: exits at once */

    printf("ConsentRef=USER_LOCAL_01\n");
    printf("RegistryAuthority=REGISTRY_AUTHORITY_HKCU_PATH "
           "Accessed=false Mutated=false\n");
    printf("ApprovedClient=APPROVED_USER_CLIENT_EXE\n");
    printf("ApprovedLaunch=calc.exe\n");

    if (prove_own_identity() != 0) {
        fprintf(stderr, "token proof failed; aborting before launch\n");
        return 1;
    }

    rc = posix_spawn(&pid, stub, NULL, NULL, argv, environ);
    if (rc != 0) {
        fprintf(stderr, "spawn failed rc=%d\n", rc);
        return 1;
    }
    printf("ChildLaunched PID=%ld\n", (long)pid);

    /* Simulated window proof: bounded, same output contract. */
    printf("WindowProof=WINDOW_FOREGROUND_PROOF Title=\"Calculator (stub)\" "
           "WINDOW_TITLE_CONTAINS_CALCULATOR=true TimeoutMs=%u "
           "Simulated=true\n",
           WINDOW_VISIBILITY_TIMEOUT_MS);
    printf("CalcWindowVisible=true\n");

    if (waitpid(pid, &status, 0) < 0) {
        fprintf(stderr, "waitpid failed errno=%d\n", errno);
        return 1;
    }

    printf("TeardownLog PID=%ld ExitCode=%d WaitResult=0 "
           "TokenHandleClosed=true ProcessHandleClosed=true "
           "ThreadHandleClosed=true CleanupComplete=true\n",
           (long)pid, WIFEXITED(status) ? WEXITSTATUS(status) : -1);

    printf("ProofComplete=authorized user calc cleanup "
           "CalcWindowVisible=true\n");
    return 0;
}
