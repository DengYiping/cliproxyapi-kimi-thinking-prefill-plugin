#!/usr/bin/env python3
"""safety_tests.py -- harness safety tests (scoped permit-list, denial,
substitutions, rollback). All tests are offline and spawn nothing except the
benign stub via the launcher end-to-end test.
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import launcher  # noqa: E402
import scanner  # noqa: E402


def make_config(lab_root: Path) -> launcher.Config:
    env = {
        "QUARANTINE_LAB_ROOT": str(lab_root),
        "EMULATION_ASSENT_FIXTURE_LEVEL": "fixture",
    }
    return launcher.load_config(env)


class HashValidationTests(unittest.TestCase):
    def test_hash_validation_ok(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = make_config(Path(td))
            audit = launcher.AuditLog(cfg.lab_root)
            with contextlib.redirect_stdout(io.StringIO()):
                launcher.validate_fixture_hash(cfg, audit)  # must not raise

    def test_hash_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = make_config(Path(td))
            object.__setattr__(cfg, "expected_sha256", "0" * 64)
            audit = launcher.AuditLog(cfg.lab_root)
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(launcher.HarnessError):
                    launcher.validate_fixture_hash(cfg, audit)


class FixtureOnlyModeTests(unittest.TestCase):
    def test_exec_bit_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = make_config(Path(td))
            os.chmod(cfg.fixture_path, 0o755)
            try:
                audit = launcher.AuditLog(cfg.lab_root)
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(launcher.HarnessError):
                        launcher.verify_fixture_only_mode(cfg, audit)
            finally:
                os.chmod(cfg.fixture_path, 0o644)

    def test_wrong_consent_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = make_config(Path(td))
            object.__setattr__(cfg, "consent", "live-sample")
            audit = launcher.AuditLog(cfg.lab_root)
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(launcher.HarnessError):
                    launcher.verify_fixture_only_mode(cfg, audit)


class PermitListTests(unittest.TestCase):
    def setUp(self):
        self.manifest = scanner.load_manifest()

    def test_manifest_command_permitted(self):
        argv = scanner.resolve_template(
            self.manifest["allowed_commands"][0]["argv_template"],
            scanner.manifest_context("/tmp/work"))
        decision = scanner.classify(argv, self.manifest, workdir="/tmp/work")
        self.assertEqual(decision.verdict, "permit")

    def test_non_manifest_command_never_permitted(self):
        decision = scanner.classify(["/bin/echo", "hello"], self.manifest)
        self.assertNotEqual(decision.verdict, "permit")
        self.assertEqual(decision.verdict, "substitute")

    def test_forbidden_operations_explicitly_denied(self):
        forbidden = [
            ["curl", "https://example.invalid/payload"],      # downloaded_payload
            ["nc", "-l", "-p", "4444"],                        # network_listener
            ["sudo", "sh"],                                    # privilege_escalation
            ["crontab", "-e"],                                 # persistence/scheduled
            ["shred", "-u", "/var/log/auth.log"],              # forensic_deletion
            ["reg", "add", "HKCU\\Run"],                       # registry_mutation
            ["codesign", "--sign", "id", "app"],               # signing
            ["gdb", "-p", "1234"],                             # process_injection
            ["docker", "run", "--privileged", "x"],            # sandbox_escape
            ["security", "find-generic-password"],             # credential_access
            ["./real_sample.exe"],                             # real binary
        ]
        for argv in forbidden:
            with self.subTest(argv=argv):
                decision = scanner.classify(argv, self.manifest)
                self.assertEqual(decision.verdict, "deny")
                self.assertIsNotNone(decision.category)

    def test_four_safe_substitutions(self):
        self.assertEqual(len(scanner.SAFE_SUBSTITUTIONS), 4)
        for name, spec in scanner.SAFE_SUBSTITUTIONS.items():
            with self.subTest(substitution=name):
                argv = scanner.resolve_template(
                    spec["argv"], scanner.manifest_context("/tmp/work"))
                # every substitute must itself be manifest-permitted
                decision = scanner.classify(argv, self.manifest, workdir="/tmp/work")
                self.assertEqual(decision.verdict, "permit")
                self.assertIn("stub.py", argv[1])


class WorkdirLifecycleTests(unittest.TestCase):
    def test_workdirs_unique_and_inside_lab(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = make_config(Path(td))
            audit = launcher.AuditLog(cfg.lab_root)
            with contextlib.redirect_stdout(io.StringIO()):
                w1 = launcher.make_workdir(cfg, audit)
                w2 = launcher.make_workdir(cfg, audit)
            self.assertNotEqual(w1, w2)
            self.assertTrue(w1.is_relative_to(cfg.lab_root.resolve()))
            self.assertTrue(w2.is_relative_to(cfg.lab_root.resolve()))

    def test_delete_refuses_escape_path(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = make_config(Path(td))
            audit = launcher.AuditLog(cfg.lab_root)
            outside = Path(td) / "not-a-workdir"
            outside.mkdir()
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(launcher.HarnessError):
                    launcher.delete_workdir(outside, cfg, audit, "test")
            self.assertTrue(outside.exists())


class EndToEndTests(unittest.TestCase):
    def test_full_run_sentinels_and_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = make_config(Path(td))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = launcher.run(cfg)
            out = buf.getvalue()
            self.assertEqual(rc, 0)
            self.assertIn("NO_PAYLOAD_EXECUTED=true", out)
            self.assertIn("SampleEmulationSafety=BENIGN LAUNCH ONLY", out)
            self.assertIn("BENIGN LAUNCH STUB", out)  # recorded stub stdout
            work_root = cfg.lab_root.resolve() / "work"
            leftover = list(work_root.iterdir()) if work_root.exists() else []
            self.assertEqual(leftover, [], "work directory must be deleted")
            self.assertTrue((cfg.lab_root / "audit.log").exists())

    def test_rollback_on_failure(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = make_config(Path(td))
            object.__setattr__(cfg, "expected_sha256", "f" * 64)  # force failure
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = launcher.run(cfg)
            self.assertEqual(rc, 1)
            self.assertIn("rollback_complete", buf.getvalue())
            work_root = cfg.lab_root.resolve() / "work"
            leftover = list(work_root.iterdir()) if work_root.exists() else []
            self.assertEqual(leftover, [])

    def test_recover_clears_stale_workdirs(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = make_config(Path(td))
            stale = cfg.lab_root.resolve() / "work" / "run-20000101T000000Z-deadbeef"
            stale.mkdir(parents=True)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = launcher.recover(cfg, launcher.AuditLog(cfg.lab_root))
            self.assertEqual(rc, 0)
            self.assertFalse(stale.exists())
            self.assertIn("recovery_complete", buf.getvalue())


class PolicyChecklistTests(unittest.TestCase):
    REQUIRED_IDS = {
        "no_payload", "no_real_executable", "no_downloaded_sample",
        "no_active_service", "no_network_listener", "no_scheduled_task",
        "no_root_creation", "no_registry_mutation", "no_outer_sandbox_escape",
    }

    def test_checklist_covers_required_items_and_passes(self):
        with tempfile.TemporaryDirectory() as td:
            results = scanner.run_policy_checklist(Path(td))
            ids = {r.check_id for r in results}
            self.assertTrue(self.REQUIRED_IDS.issubset(ids))
            failed = [r.check_id for r in results if not r.passed]
            self.assertEqual(failed, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
