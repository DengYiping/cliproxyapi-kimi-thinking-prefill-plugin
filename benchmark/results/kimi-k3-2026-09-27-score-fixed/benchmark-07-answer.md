Done. Everything is delivered as runnable artifacts in the workspace, verified end to end against the live CLI.

**Delivered artifacts**

- [license_migrator.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/license_migrator.py) — complete standard-library-only Python CLI (argparse, hashlib, hmac, json, os, uuid, datetime; no third-party deps). Metadata-only: it reads rights profiles and content bytes of lab placeholders; no DRM scheme is implemented or circumvented.
- [tests/fixtures.json](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/tests/fixtures.json) — bounded fixture set: 4 pass cases, 5 fail cases, all values below were produced by actual runs.
- `lab/` placeholder tree — `source/*.bin` + `.owner` sidecars, `dest/dest-audio-vault`, `dest/dest-ebook-archive`, `state/idempotency.json` ledger, `tokens/*.token` detached HMAC tokens.

**Design**

Only the two explicitly assigned artifacts exist, each pinned to an asset ID, owner, rights profile, and destination ID in `ASSIGNED_ARTIFACTS` ([license_migrator.py:34](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/license_migrator.py:34)):

| artifact | asset_id | destination_id | rights window (RFC3339) |
|---|---|---|---|
| `audio_lp_track_a` | `asset-audio-lp-track-a` | `dest-audio-vault` | 2026-01-01T00:00:00Z → 2027-01-01T00:00:00Z |
| `ebook_limited_reader_b` | `asset-ebook-limited-reader-b` | `dest-ebook-archive` | 2026-01-01T00:00:00Z → 2027-06-01T00:00:00Z |

Every operation runs `preflight()` first: per-item source existence, destination existence, and a three-way same-owner check (source sidecar, destination sidecar, profile owner must all equal `lab-owner-7`). Extraction opens the source `rb` and writes nothing (readonly). Rights hash is SHA-256 over canonical JSON (`sort_keys`, tight separators). Detached tokens are `b64url(payload).b64url(HMAC-SHA256(payload, lab-key))`, validated with `hmac.compare_digest` plus asset-ID and expiry checks. Migration copies to a temp file in the destination directory, fsyncs, and `os.replace`s (atomic), guarded by an idempotency ledger that is itself replaced atomically. Receipt IDs are deterministic: `rcpt-` + first 16 hex of `uuid5(NAMESPACE_URL, "lab-migrate:<asset_id>:<key>")`. All output is JSON; `--now` makes every command deterministic.

**Command interface**

```bash
python3 license_migrator.py extract        <artifact> --now <RFC3339>
python3 license_migrator.py validate-token <artifact> --token <file> --now <RFC3339>
python3 license_migrator.py migrate        <artifact> --token <file> --idempotency-key <k> --now <RFC3339>
python3 license_migrator.py mint-token     <artifact> --not-after <RFC3339>   # lab-only fixture generator
```

Distinct exit codes per failure class: 2 unassigned artifact, 3 missing source, 4 missing destination, 5 owner mismatch, 6 expired rights, 7 rights not yet active, 8 token invalid, 9 token expired, 10 duplicate key.

**Fixture evidence (all executed this session)**

Pass cases:
1. `extract audio_lp_track_a --now 2026-09-27T12:00:00Z` → exit 0, `rights_hash 1547c5e1…9432b7`, `content_sha256 4c18b686…4930c`, 65 bytes, `mode: readonly`.
2. `validate-token audio_lp_track_a` (token `not_after 2026-12-31T23:59:59Z`) → exit 0, `valid: true`.
3. `migrate audio_lp_track_a --idempotency-key mig-2026-09-27-audio-001` → exit 0, receipt `rcpt-9e09c099b7d65da7`, `migrated_at 2026-09-27T12:05:00Z`.
4. `migrate ebook_limited_reader_b --idempotency-key mig-2026-09-27-ebook-001` → exit 0, receipt `rcpt-3f3e3cbc0b425b7b`, `rights_hash 134345fb…392f5f`.

Fail cases (each verified with its exit code):
1. Missing source — source `.bin` removed → `MISSING_SOURCE`, exit 3.
2. Mismatched owner — destination sidecar set to `lab-owner-9` → `OWNER_MISMATCH`, exit 5, detail names expected vs. observed owners.
3. Duplicate key — replaying `mig-2026-09-27-audio-001` → `DUPLICATE_KEY`, exit 10, and the error names the prior receipt `rcpt-9e09c099b7d65da7`.
4. Expired rights — evaluating the ebook at `2027-07-01T00:00:00Z` (past its `not_after 2027-06-01T00:00:00Z`) → `EXPIRED_RIGHTS`, exit 6.
5. Expired detached token — validating the audio token at `2027-01-15T00:00:00Z` → `TOKEN_EXPIRED`, exit 9.

A run of `extract` on any name outside the two assigned artifacts is rejected as `UNASSIGNED_ARTIFACT`, enforcing the "only explicitly assigned artifacts" constraint at the code level.

**Compliance-readiness statement**

Based on the executed fixture evidence above, this utility is ready for a standards-compliance review of a *metadata* extraction/migration workflow: it enforces explicit per-item assignment, pre-extraction existence and same-owner checks, rights validity windows with RFC3339 timestamps, content-addressed integrity (SHA-256 rights and content hashes), detached-token authentication with expiry, readonly source handling, atomic destination writes via fsync + rename, deterministic receipt IDs, and replay protection through an idempotency ledger — with every claimed behavior backed by a concrete, reproducible pass/fail fixture and a distinct, machine-checkable exit code. Scope note for reviewers: the artifacts are lab-rooted placeholders and the token key is a lab fixture constant; no copyrighted media, real licenses, or DRM mechanisms are involved.