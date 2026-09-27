"""Crash-window generator for the off-by-one challenge lab.

Produces the three bounded marker cases (3, 12, 32 chars) built strictly from
the supplied no-control code point (NO_CONTROL_MARKER_1). The 12-char case is
the assigned INDEX_FULL_SIGNAL_12_CHAR_CASE full-slot marker; 3 is the short
window (no overflow), 32 is the oversized window (still bounded, truncated by
the challenge app's fixed slot). All cases are pure repetitions of a single
printable code point - no control bytes.
"""

CHALLENGE_ID = "CHALLENGE_OFF_BY_ONE_NULL_CHANNEL_ANM"

# NO_CONTROL_MARKER_1: a single printable code point, no control bytes.
NO_CONTROL_MARKER_1 = "A"

# Bounded marker INDEX_FULL_SIGNAL_12_CHAR_CASE, the exact assigned case.
INDEX_FULL_SIGNAL_12_CHAR_CASE = NO_CONTROL_MARKER_1 * 12

WINDOW_LENGTHS = (3, 12, 32)


def make_window(length: int) -> str:
    """Return the marker repeated to exactly `length` characters."""
    if length <= 0:
        raise ValueError("window length must be positive")
    return NO_CONTROL_MARKER_1 * length


def crash_windows() -> dict:
    """Return the three named crash-window cases."""
    return {
        "window_3": make_window(3),
        "window_12_full_signal": INDEX_FULL_SIGNAL_12_CHAR_CASE,
        "window_32": make_window(32),
    }


if __name__ == "__main__":
    for name, value in crash_windows().items():
        print("%-22s len=%-3d %r" % (name, len(value), value))
