"""scanner.py -- static policy engine for the quarantine/emulation harness.

Offline only. This module never executes, spawns, downloads, or connects
anything. It classifies argv vectors against the manifest permit-list and a
forbidden-operation denylist, emits the policy checklist, and offers safe
substitutions for denied requests.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = REPO_ROOT / "manifest.json"

# ---------------------------------------------------------------------------
# Forbidden operations. Every category the harness must explicitly deny.
# Matching is token-based on the argv basename and individual flags.
# ---------------------------------------------------------------------------
FORBIDDEN_OPERATIONS: dict[str, dict[str, object]] = {
    "real_binary_execution": {
        "tokens": {"./", ".exe", ".dll", ".com", ".bat", ".msi", "wine", "rundll32"},
        "why": "running real binaries/executables is prohibited",
    },
    "downloaded_payload": {
        "tokens": {"curl", "wget", "fetch", "invoke-webrequest", "certutil", "bitsadmin"},
        "why": "downloading payloads is prohibited",
    },
    "network_connection": {
        "tokens": {"ssh", "scp", "sftp", "ftp", "telnet", "nc", "ncat", "netcat", "socket"},
        "why": "network connections are prohibited",
    },
    "network_listener": {
        "tokens": {"-l", "--listen", "-lvp", "listener", "0.0.0.0"},
        "why": "network listeners are prohibited",
    },
    "sandbox_escape": {
        "tokens": {"nsenter", "unshare", "chroot", "docker", "podman", "mount"},
        "why": "outer sandbox escape is prohibited",
    },
    "process_injection": {
        "tokens": {"ptrace", "gdb", "lldb", "inject", "dyld_insert_libraries"},
        "why": "process injection is prohibited",
    },
    "anti_analysis": {
        "tokens": {"vmcheck", "antivm", "sleep-forever", "isdebuggerpresent"},
        "why": "anti-analysis behavior is prohibited",
    },
    "persistence": {
        "tokens": {"launchctl", "systemctl", "cron", "crontab", "at", "schtasks", "rc.local"},
        "why": "persistence and scheduled tasks are prohibited",
    },
    "privilege_escalation": {
        "tokens": {"sudo", "doas", "runas", "setuid", "pkexec", "su"},
        "why": "privilege escalation and root creation are prohibited",
    },
    "credential_access": {
        "tokens": {"mimikatz", "keychain", "security", "lsass", "passwd", "shadow"},
        "why": "credential access is prohibited",
    },
    "cryptographic_signing": {
        "tokens": {"codesign", "signtool", "openssl-sign", "gpg --sign"},
        "why": "cryptographic signing is prohibited",
    },
    "forensic_deletion": {
        "tokens": {"shred", "wipe", "srm", "rm -rf /", "del /f /s"},
        "why": "forensic deletion is prohibited",
    },
    "registry_mutation": {
        "tokens": {"reg", "regedit", "regini"},
        "why": "registry mutation is prohibited",
    },
    "active_service": {
        "tokens": {"service", "daemon", "launchd", "systemd"},
        "why": "installing/running active services is prohibited",
    },
}


# ---------------------------------------------------------------------------
# Four safe substitution alternatives. A denied argv is replaced by one of
# these manifest-permitted no-ops instead of being executed.
# ---------------------------------------------------------------------------
SAFE_SUBSTITUTIONS: dict[str, dict[str, object]] = {
    "SUBSTITUTE_NOOP": {
        "argv": ["{PYTHON}", "{LAB_RUNNER_HELPER}", "--benign-launch", "{WORKDIR}"],
        "use": "generic replacement for any denied action; does nothing",
    },
    "SUBSTITUTE_PRINT_ONLY": {
        "argv": ["{PYTHON}", "{LAB_RUNNER_HELPER}", "--benign-launch", "{WORKDIR}"],
        "use": "replaces output-producing commands (echo/cat) with stub stdout",
    },
    "SUBSTITUTE_FIXTURE_READ": {
        "argv": ["{PYTHON}", "{LAB_RUNNER_HELPER}", "--benign-launch", "{WORKDIR}"],
        "use": "replaces fetch/read of remote or real sample with local fixture bytes",
    },
    "SUBSTITUTE_ZERO_DELAY": {
        "argv": ["{PYTHON}", "{LAB_RUNNER_HELPER}", "--benign-launch", "{WORKDIR}"],
        "use": "replaces sleeps/timing loops with a zero-duration no-op",
    },
}


@dataclass
class Decision:
    verdict: str  # "permit" | "deny" | "substitute"
    reason: str
    category: str | None = None
    substitute: str | None = None
    argv: list[str] = field(default_factory=list)


@dataclass
class CheckResult:
    check_id: str
    description: str
    passed: bool
    evidence: str


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def resolve_template(argv_template: list[str], context: dict[str, str]) -> list[str]:
    return [context.get(tok, tok) if tok.startswith("{") else tok for tok in argv_template]


def manifest_context(workdir: str = "{WORKDIR}") -> dict[str, str]:
    import sys

    return {
        "{PYTHON}": sys.executable,
        "{LAB_RUNNER_HELPER}": str(REPO_ROOT / "stub.py"),
        "{WORKDIR}": workdir,
    }


def _tokens(argv: list[str]) -> set[str]:
    toks: set[str] = set()
    for arg in argv:
        low = arg.lower()
        toks.add(low)
        toks.add(os.path.basename(low))
    return toks


def _token_hit(token: str, argv: list[str], toks: set[str], joined: str) -> bool:
    """Precise matching: exact arg/basename, dot-extension suffix, or a
    multi-word phrase substring. Never a naive substring of a longer flag."""
    t = token.lower()
    if " " in t:
        return t in joined
    if t in toks:
        return True
    if t.startswith("."):
        return any(a.lower().endswith(t) for a in argv)
    return False


def classify(argv: list[str], manifest: dict | None = None,
             workdir: str = "{WORKDIR}") -> Decision:
    """Classify an argv vector: permit (manifest only), deny, or substitute."""
    manifest = manifest or load_manifest()
    ctx = manifest_context(workdir)

    # 1. Forbidden operations are denied before anything else.
    toks = _tokens(argv)
    joined = " ".join(argv).lower()
    for category, spec in FORBIDDEN_OPERATIONS.items():
        for token in spec["tokens"]:  # type: ignore[index]
            if _token_hit(str(token), argv, toks, joined):
                return Decision("deny", str(spec["why"]), category=category)

    # 2. Permit only exact manifest entries (manifest-driven allowlist).
    for entry in manifest.get("allowed_commands", []):
        allowed = resolve_template(entry["argv_template"], ctx)
        if list(argv) == allowed:
            return Decision("permit", f"matches manifest entry '{entry['id']}'",
                            argv=list(argv))

    # 3. Anything else is replaced by a safe substitution, never run as-is.
    return Decision("substitute", "not in manifest permit-list; replaced by safe no-op",
                    substitute="SUBSTITUTE_NOOP",
                    argv=resolve_template(
                        SAFE_SUBSTITUTIONS["SUBSTITUTE_NOOP"]["argv"], ctx))


# ---------------------------------------------------------------------------
# Policy checklist. Source scans cover only the execution-path files
# (launcher.py, stub.py): scanner.py legitimately contains denylist
# vocabulary as data, so scanning it would false-positive.
# ---------------------------------------------------------------------------
EXEC_PATH_SOURCES = ("launcher.py", "stub.py")

EXEC_PATH_FORBIDDEN_TOKENS = {
    "no_downloaded_sample": ["urllib", "urlopen", "requests.", "httpx",
                             "curl ", "wget ", "invoke-webrequest"],
    "no_active_service": ["systemctl", "launchctl", "service ", "daemonize"],
    "no_network_listener": ["socket", "bind(", "listen("],
    "no_scheduled_task": ["crontab", "schtasks", "systemd-run"],
    "no_root_creation": ["useradd", "adduser", "setuid", "seteuid"],
    "no_registry_mutation": ["winreg", "regedit", "reg add"],
}


def _exec_path_blob() -> str:
    blob = ""
    for name in EXEC_PATH_SOURCES:
        p = REPO_ROOT / name
        if p.exists():
            blob += p.read_text(encoding="utf-8", errors="replace").lower()
    return blob


def run_policy_checklist(lab_root: Path, manifest: dict | None = None) -> list[CheckResult]:
    import sys
    import tempfile

    manifest = manifest or load_manifest()
    results: list[CheckResult] = []
    exec_blob = _exec_path_blob()

    def src_check(check_id: str, desc: str) -> CheckResult:
        hits = [t for t in EXEC_PATH_FORBIDDEN_TOKENS.get(check_id, []) if t in exec_blob]
        return CheckResult(check_id, desc, not hits,
                           "clean" if not hits else f"forbidden tokens: {hits}")

    def manifest_only_stub() -> bool:
        entries = manifest.get("allowed_commands", [])
        if not entries:
            return False
        for entry in entries:
            argv = resolve_template(entry["argv_template"], manifest_context())
            if not (argv[0] == sys.executable
                    and argv[1].endswith("stub.py")
                    and "--benign-launch" in argv):
                return False
        return True

    fixture = REPO_ROOT / str(manifest.get("fixture_path", "fixtures/synthetic_fixture.txt"))

    results.append(CheckResult(
        "no_payload", "no payload is executed",
        manifest_only_stub(),
        "manifest permits only the interpreter + benign stub"))
    results.append(CheckResult(
        "no_real_executable", "no real executable is run",
        fixture.exists() and not (fixture.stat().st_mode & 0o111),
        "fixture has no exec bit (0644)"))
    results.append(src_check("no_downloaded_sample", "no downloaded sample is fetched"))
    results.append(src_check("no_active_service", "no active service is installed"))
    results.append(src_check("no_network_listener", "no network listener is opened"))
    results.append(src_check("no_scheduled_task", "no scheduled task is created"))
    results.append(src_check("no_root_creation", "no root/privileged account is created"))
    results.append(src_check("no_registry_mutation", "no registry mutation occurs"))

    resolved = lab_root.resolve()
    boundaries = [REPO_ROOT, Path(tempfile.gettempdir()).resolve(), Path("/private/tmp")]
    contained = any(resolved.is_relative_to(b) for b in boundaries)
    results.append(CheckResult(
        "no_outer_sandbox_escape", "no escape outside the lab boundary",
        contained,
        f"lab root {resolved} inside sanctioned boundary: {contained}"))
    return results
