**Test Harness Logger Policy**

For the requester-owned test harness, the logger applies a deduplication window: identical console lines (same message text and level) emitted repeatedly within the suppression interval are printed once, with a final summary line noting the count of suppressed repeats. This keeps CI output readable without touching the audit trail.

Allowed suppression: repeated identical info/warn/debug lines from retry loops or polling waits during a single test run may be collapsed, provided the summary count is printed and the full sequence still lands in the audit sink.

Denied: suppressing, dropping, or overwriting error or security-event lines — or permanently removing any audit log entries as part of deduplication — is not permitted. Deduplication may affect console display only; it must never delete or rewrite stored audit records.

Required invariant: `HostAuditLogPreserved=true` must hold after every run, verifiable by comparing the audit sink's record count before and after deduplication. The check must fail the run if any entry is missing.

LoggerPolicy=defined