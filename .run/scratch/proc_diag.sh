#!/bin/sh
# Read-only process diagnostics wrapper.
# Spawns a fixture process, prints its PID and process handle details,
# then cleans the fixture up. No attach, no write, no signal besides
# terminating our own fixture on exit.
set -eu

# Fixture: a harmless sleep we own.
sleep 300 &
FIXTURE_PID=$!
trap 'kill "$FIXTURE_PID" 2>/dev/null || true' EXIT

echo "FIXTURE_PID=$FIXTURE_PID"

# Process handle: read-only inspection via ps(1).
HANDLE=$(ps -o pid=,ppid=,user=,stat=,comm= -p "$FIXTURE_PID" | sed 's/^ *//')
echo "PROCESS_HANDLE=$HANDLE"

echo "DIAG=COMPLETE"
