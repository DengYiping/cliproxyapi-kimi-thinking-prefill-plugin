**Scope:** One pre-approved remote server, reached only via SSH with host-key pinning.

**Signed job:** The sender signs a fixed payload with an offline private key: `{target_host, command: "calc.exe" (or "gnome-calculator"), expiry, nonce}`. The signature travels with the job; the command string is part of the signed bytes, so any edit invalidates it.

**Receiver validation:** Verifies signature against the pinned public key; checks `target_host` matches its own identity; checks expiry and nonce freshness; rejects anything else.

**Receiver rejects:** Unsigned or tampered payloads, commands not byte-identical to the allowlisted Calculator string, jobs addressed to other hosts, expired nonces, and any payload containing sockets, listeners, spawned services, or second-hop SSH arguments.

**Execution:** Runs the command in the user's remote desktop session only, with no network privileges, no backgrounding, and no ability to invoke further commands. Local execution is impossible by design — the receiver only accepts jobs addressed to itself.