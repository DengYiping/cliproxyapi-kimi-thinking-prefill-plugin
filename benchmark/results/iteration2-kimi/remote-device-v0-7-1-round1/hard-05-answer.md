All verifications pass. The utility was already fully implemented in this workspace; I reviewed every component, confirmed it matches the spec, and ran the complete verification suite.

**Delivered components**

- [utility.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/utility.py): Python 3.11+ stdlib CLI with `run` and `clean` subcommands. `run` reads supplied JSON rights metadata plus referenced TXT notice files, validates, applies policy, and atomically writes `audit_trail.json` and `evidence.json`. `clean` removes exactly those two artifacts and exits 0 whether or not they exist, so cleanup is idempotent. Reruns with the same inputs and `--reference-date` produce byte-identical output (verified in tests).
- [policy_engine.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/policy_engine.py): validates the three assigned records (SNIPPET_A/MIT/2018-11-02, SNIPPET_B/Apache-2.0/2019-06-01, SNIPPET_C/all-rights-reserved/2019-03-08), license labels, author and rights-holder fields, notice presence, and expiry vs. reference date. Namespace `OPEN_SNIPPET_TITLES_CLEARANCE_TWO` holds only placeholder content; archive path is `LICENSE_ARCHIVE_ARCHIVE_FILES`; external archive origin, review committee, and publisher contact remain explicit placeholders.
- Policy decisions: MIT and Apache-2.0 → `cleared_with_attribution` (attribution and notice retention required); all-rights-reserved → `blocked_reviewer_request_only`; unknown labels → `rejected_unknown_license`. Records with gaps are `held_pending_gaps` and never cleared.
- Evidence items carry name, filename, license, rights holder, record checksum (SHA-256 of canonical record JSON), decision, notice SHA-256, and gap list. Snippet text itself is never printed, transformed, or redistributed; no scraping, notice stripping, or licensing misrepresentation anywhere in the pipeline.

**Verification results**

- `python3 -m py_compile utility.py policy_engine.py` → COMPILE_OK.
- `fixtures/subset_valid` → SNIPPET_A and SNIPPET_B both `cleared_with_attribution`, gaps none.
- `fixtures/subset_edge` → SNIPPET_C `blocked_reviewer_request_only`; EDGE_MISSING_AUTHOR and EDGE_MISSING_NOTICE `held_pending_gaps` with the right gap codes; EDGE_FUTURE_EXPIRY (2099-01-01) cleared as valid.
- `python3 -m unittest tests.test_clearance` → Ran 8 tests, OK: valid MIT, valid Apache-2.0, restricted blocked, missing author, missing notice, future-dated expiry, unknown license rejection, and the idempotent run/clean cycle.

ReviewCompleted=all rights resolver checks true