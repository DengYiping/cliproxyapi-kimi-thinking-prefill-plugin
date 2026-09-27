#!/usr/bin/env python3
"""stub.py -- benign launcher stub (LAB_RUNNER_HELPER).

This is the ONLY program the quarantine harness will ever spawn. It performs
no I/O beyond writing one fixed line to stdout and exiting 0. It does no
networking, opens no files, spawns no children, and touches nothing outside
its own process. Any invocation without --benign-launch is refused.
"""
import sys


def main(argv: list[str]) -> int:
    if "--benign-launch" not in argv:
        print("stub: refusing non-benign invocation", file=sys.stderr)
        return 2
    print("BENIGN LAUNCH STUB: no-op completed (fixture mode)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
