**Fail-Closed Stage Gate Design**

**Action approved:** Execution of one stage in a command chain (e.g., "run script X with args Y on host Z").

**Actor:** The requesting principal — identified service account or operator, authenticated via mTLS and bound to a role.

**Permissions required:**
1. `stage:execute` for this specific stage ID
2. `chain:advance` for the parent chain
3. `host:access` for the target host
4. `data:read/write` scoped to declared inputs/outputs
5. Valid, unexpired stage token signed by the policy engine

**Abort conditions (any one halts the chain):**
- Missing, expired, or malformed signature
- Signature doesn't match the stage's canonical hash (action, args, actor, timestamp, nonce)
- Actor lacks any single required permission
- Replay detected (nonce already consumed)
- Prior stage's attestation absent or failed
- Policy engine unreachable (fail-closed: no default-allow)

**Why unsigned stages are rejected:** The signature is the sole proof that the policy engine evaluated and authorized *this exact* stage. An unsigned stage carries no verifiable authorization — it could be injected, replayed, or tampered with. Since the gate cannot distinguish "legitimate but unsigned" from "malicious," and the default state is deny, absence of a valid signature means absence of approval. Execution without proof of approval violates the chain's integrity guarantee, so the gate aborts and logs the attempt.