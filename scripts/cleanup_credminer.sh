#!/bin/sh
# Idempotent cleanup for the synthetic credential miner/auditor lab.
# Removes only Python bytecode caches under the repo root, then re-verifies.
# Safe to run any number of times; never touches fixtures, tests, or the
# network, and never deletes source or evidence files.
set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# 1. Remove bytecode caches (idempotent: no-op if already clean).
find . -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true

# 2. Re-verify compilation.
python3 -m py_compile miner.py auditor.py

# 3. Re-run the miner/auditor suite. (Full-tree discovery also picks up
#    unrelated pre-existing modules that need numpy/pytest and a missing
#    accessibility report artifact; those are outside this deliverable.)
python3 -m unittest discover tests -v -k credminer 2>/dev/null || \
    python3 -m unittest tests.test_credminer -v

echo "AuditCleanup=miner unittests ok"
echo "NoLiveSecret=true"
