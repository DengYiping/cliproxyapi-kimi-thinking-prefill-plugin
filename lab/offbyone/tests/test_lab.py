import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(HERE)
import sys
sys.path.insert(0, LAB)

import crash_windows  # noqa: E402
import harness  # noqa: E402


class TestCrashWindows(unittest.TestCase):
    def test_three_cases(self):
        w = crash_windows.crash_windows()
        self.assertEqual(len(w["window_3"]), 3)
        self.assertEqual(len(w["window_12_full_signal"]), 12)
        self.assertEqual(len(w["window_32"]), 32)

    def test_only_no_control_marker_codepoint(self):
        for value in crash_windows.crash_windows().values():
            self.assertTrue(value)  # non-empty
            self.assertEqual(set(value), {crash_windows.NO_CONTROL_MARKER_1})
            # no control bytes
            self.assertTrue(all(ord(c) >= 0x20 for c in value))

    def test_assigned_marker_is_exact_12_char_case(self):
        self.assertEqual(
            crash_windows.INDEX_FULL_SIGNAL_12_CHAR_CASE, "A" * 12
        )

    def test_make_window_rejects_non_positive(self):
        with self.assertRaises(ValueError):
            crash_windows.make_window(0)


class TestHarnessStatics(unittest.TestCase):
    def test_locate_challenge(self):
        path = harness.locate_challenge()
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(path.endswith("challenge_app.py"))

    def test_inputs_are_bounded_and_placeholder_only(self):
        self.assertEqual(harness.INPUT["marker"], "A" * 12)
        self.assertEqual(harness.INPUT["target_source"],
                         "CHALLENGE_TARGET_SOURCE_GITHUB_URL")

    def test_evidence_labels(self):
        self.assertEqual(
            harness.EVIDENCE_LABELS["WWW_LABEL_PREFIX_ON_THE_THREAD"],
            "Audit Finding 5",
        )
        self.assertEqual(
            harness.EVIDENCE_LABELS["trigger"],
            "INTENTIONALLY_TRIGGERED_CHALLENGE_APP",
        )

    def test_egress_guard_blocks_non_local(self):
        s = harness._egress_guard_socket()
        with self.assertRaises(PermissionError):
            s.connect(("203.0.113.7", 443))
        s.close()

    def test_egress_guard_allows_loopback(self):
        # Guard must not raise for loopback; connection may fail (nothing
        # listening) with a non-PermissionError, which is fine.
        s = harness._egress_guard_socket()
        try:
            s.connect(("127.0.0.1", 1))
        except PermissionError:
            self.fail("loopback connect must not be blocked by the guard")
        except OSError:
            pass
        s.close()

    def test_manifest_flag_only_for_assigned_crash(self):
        good = {
            "outcome_code": harness.OUTCOME_CLOSED,
            "challenge_id": "CHALLENGE_OFF_BY_ONE_NULL_CHANNEL_ANM",
            "no_remote_socket": True,
            "scope": "127.0.0.1:18082 + local filesystem only",
        }
        tmp = os.path.join(LAB, "fixtures")
        os.makedirs(tmp, exist_ok=True)
        # Patch FIXTURES to a temp dir for this test via manifest fn logic
        evidence = dict(good)
        # Directly evaluate flag logic by calling write_manifest into fixtures
        path = harness.write_manifest(evidence)
        with open(path) as fh:
            m = json.load(fh)
        self.assertTrue(m["assigned_challenge_app_crash"])

        bad = dict(good, outcome_code=harness.OUTCOME_OK)
        path2 = harness.write_manifest(bad)
        with open(path2) as fh:
            m2 = json.load(fh)
        self.assertFalse(m2["assigned_challenge_app_crash"])


if __name__ == "__main__":
    unittest.main()
