**Sender:** Connects only to the approved host `calc-server.example.com` over SSH with a pinned host key. It sends a job envelope: `{job_id, command: "/usr/bin/gnome-calculator", display: ":0", expiry, signature}` signed with the sender's Ed25519 key. The command field is a fixed constant — no user-supplied arguments.

**Receiver (on calc-server only):**
1. Verifies the Ed25519 signature against the sender's pinned public key; rejects on mismatch.
2. Rejects expired or replayed job_ids (nonce cache).
3. Rejects any command not byte-identical to the allowlisted `/usr/bin/gnome-calculator` — no shell parsing, no arguments, no path substitution.
4. Rejects any request to bind sockets, forward ports, or spawn daemons; SSH session requests `no-pty`, no forwarding.
5. Executes via `execve` directly (no shell) as an unprivileged user on the existing local display `:0`, then closes the session.

Anything failing validation is logged and dropped.