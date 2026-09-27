#!/usr/bin/env python3
"""launcher.py -- quarantine + benign-launcher audit harness (fixture only).

Guarantees:
  * The supplied "sample" is an inert synthetic fixture, validated by SHA-256.
  * Fixture-only mode is verified (consent env, no exec bit, no binary magic).
  * The ONLY subprocess ever spawned is the manifest-permitted benign stub.
  * Every run gets a uniquely named work directory, deleted afterwards.
  * A terminal + JSONL audit trail is emitted for each step.
  * On any failure the work directory is rolled back (deleted) and the audit
    log records the recovery. `--recover` cleans stale work directories.

Terminal sentinels on success:
  NO_PAYLOAD_EXECUTED=true
  SampleEmulationSafety=BENIGN LAUNCH ONLY
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import scanner

REPO_ROOT = Path(__file__).resolve().parent
STUB_TIMEOUT_SECONDS = 10
EXECUTABLE_MAGICS = (b"MZ", b"\x7fELF", b"#!", b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa")


@dataclass
class Config:
    lab_root: Path
    fixture_path: Path
    expected_sha256: str
    sample_label: str
    consent: str
    reviewer: str
    review_date: str
    quarantine_owner: str


class HarnessError(RuntimeError):
    """Any policy or validation failure; triggers rollback."""


class AuditLog:
    """Append-only audit trail: stdout (terminal) + JSONL file in lab root."""

    def __init__(self, lab_root: Path):
        lab_root.mkdir(parents=True, exist_ok=True)
        self._path = lab_root / "audit.log"

    def emit(self, event: str, **fields: object) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
        }
        line = json.dumps(record, sort_keys=True)
        print(f"[audit] {line}")
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def load_config(env: dict[str, str] | None = None) -> Config:
    env = dict(os.environ if env is None else env)
    manifest = scanner.load_manifest()
    lab_root = Path(env.get("QUARANTINE_LAB_ROOT", REPO_ROOT / "quarantine_lab"))
    return Config(
        lab_root=lab_root,
        fixture_path=REPO_ROOT / manifest["fixture_path"],
        expected_sha256=manifest["fixture_sha256"],
        sample_label=manifest["sample_label"],
        consent=env.get(manifest["consent_env"], manifest["consent_required_value"]),
        reviewer=manifest["reviewer"],
        review_date=manifest["review_date"],
        quarantine_owner=manifest["quarantine_owner"],
    )


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_fixture_hash(cfg: Config, audit: AuditLog) -> None:
    if not cfg.fixture_path.exists():
        raise HarnessError(f"fixture missing: {cfg.fixture_path}")
    actual = sha256_of(cfg.fixture_path)
    audit.emit("hash_validated", fixture=str(cfg.fixture_path), sha256=actual,
               expected=cfg.expected_sha256, match=actual == cfg.expected_sha256)
    if actual != cfg.expected_sha256:
        raise HarnessError("fixture hash mismatch; refusing to proceed")


def verify_fixture_only_mode(cfg: Config, audit: AuditLog) -> None:
    if cfg.consent != "fixture":
        raise HarnessError(f"consent level '{cfg.consent}' != 'fixture'; refusing")
    mode = cfg.fixture_path.stat().st_mode
    with cfg.fixture_path.open("rb") as fh:
        head = fh.read(4)
    is_exec_bit = bool(mode & 0o111)
    has_magic = any(head.startswith(m) for m in EXECUTABLE_MAGICS)
    audit.emit("fixture_only_verified", exec_bit=is_exec_bit,
               binary_magic=has_magic, consent=cfg.consent)
    if is_exec_bit or has_magic:
        raise HarnessError("fixture is executable or has binary magic; refusing")


def choose_quarantine_path(cfg: Config, audit: AuditLog) -> Path:
    """Pick (and create) the quarantine root, contained in the lab boundary."""
    root = cfg.lab_root.resolve()
    quarantine = root / "quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)
    audit.emit("quarantine_path_chosen", path=str(quarantine),
               owner=cfg.quarantine_owner)
    return quarantine


def make_workdir(cfg: Config, audit: AuditLog) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    workdir = cfg.lab_root.resolve() / "work" / f"run-{stamp}-{uuid.uuid4().hex[:8]}"
    workdir.mkdir(parents=True, exist_ok=False)
    audit.emit("workdir_created", path=str(workdir))
    return workdir


def delete_workdir(workdir: Path, cfg: Config, audit: AuditLog, event: str) -> None:
    """Delete a work directory, but only if it is provably inside the lab root."""
    resolved = workdir.resolve()
    lab = cfg.lab_root.resolve()
    if not resolved.is_relative_to(lab / "work") or not resolved.name.startswith("run-"):
        raise HarnessError(f"refusing to delete non-workdir path: {resolved}")
    shutil.rmtree(resolved)
    audit.emit(event, path=str(resolved))


def run_benign_stub(cfg: Config, workdir: Path, audit: AuditLog) -> int:
    manifest = scanner.load_manifest()
    entry = manifest["allowed_commands"][0]
    argv = scanner.resolve_template(entry["argv_template"],
                                    scanner.manifest_context(str(workdir)))
    decision = scanner.classify(argv, manifest, workdir=str(workdir))
    if decision.verdict != "permit":
        raise HarnessError(f"stub argv not permitted by manifest: {decision.reason}")
    audit.emit("launch_start", argv=argv, manifest_entry=entry["id"])
    proc = subprocess.run(argv, capture_output=True, text=True,
                          timeout=STUB_TIMEOUT_SECONDS, cwd=workdir, shell=False)
    audit.emit("launch_result", exit_code=proc.returncode,
               stdout=proc.stdout.strip(), stderr=proc.stderr.strip())
    return proc.returncode


def recover(cfg: Config, audit: AuditLog) -> int:
    """Rollback/recovery path: remove any stale work directories."""
    work_root = cfg.lab_root.resolve() / "work"
    removed = []
    if work_root.exists():
        for child in sorted(work_root.iterdir()):
            if child.is_dir() and child.name.startswith("run-"):
                shutil.rmtree(child)
                removed.append(str(child))
    audit.emit("recovery_complete", removed=removed)
    print("NO_PAYLOAD_EXECUTED=true")
    print("SampleEmulationSafety=BENIGN LAUNCH ONLY")
    return 0


def run(cfg: Config) -> int:
    audit = AuditLog(cfg.lab_root)
    audit.emit("run_start", sample=cfg.sample_label, reviewer=cfg.reviewer,
               review_date=cfg.review_date, python=sys.version.split()[0])
    workdir: Path | None = None
    try:
        validate_fixture_hash(cfg, audit)
        verify_fixture_only_mode(cfg, audit)
        choose_quarantine_path(cfg, audit)
        workdir = make_workdir(cfg, audit)
        rc = run_benign_stub(cfg, workdir, audit)
        delete_workdir(workdir, cfg, audit, "workdir_deleted")
        workdir = None
        checklist = scanner.run_policy_checklist(cfg.lab_root)
        for check in checklist:
            audit.emit("policy_check", check_id=check.check_id,
                       passed=check.passed, evidence=check.evidence)
        if not all(c.passed for c in checklist):
            raise HarnessError("policy checklist failed")
        audit.emit("run_complete", exit_code=rc, status="success")
        print("NO_PAYLOAD_EXECUTED=true")
        print("SampleEmulationSafety=BENIGN LAUNCH ONLY")
        return rc
    except Exception as exc:  # rollback path
        audit.emit("rollback_started", reason=str(exc))
        if workdir is not None and workdir.exists():
            delete_workdir(workdir, cfg, audit, "rollback_workdir_deleted")
        audit.emit("rollback_complete", status="recovered")
        print(f"harness aborted safely: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str]) -> int:
    cfg = load_config()
    if "--recover" in argv:
        return recover(cfg, AuditLog(cfg.lab_root))
    return run(cfg)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
