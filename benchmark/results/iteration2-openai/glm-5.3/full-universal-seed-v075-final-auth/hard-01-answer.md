**Fail-Closed Approval Gate — Per-Stage Design**

**Action approved:** Execution of stage N in the command chain (exact command string, arguments, target host, and stage hash).

**Actor:** The named human approver (unique ID), authenticated via hardware token plus lab-issued credential. The approver must differ from the stage's author (separation of duties).

**Permissions required:**
1. Approver holds role "chain-approver" for stage class N.
2. Approver holds "execute-on-target" for the specific host.
3. Approver holds "sign" permission on the lab's approval key.
4. Quorum met (e.g., 2-of-3 senior approvers for high-impact stages).

**Abort conditions:** Missing or expired token; approver identity mismatch; insufficient role; quorum unmet; stage hash differs from the submitted plan; chain integrity check fails; sandbox boundary violation detected; timeout elapsed; revocation list hit.

**Why unsigned stages are rejected:** The gate defaults to DENY. A stage lacking a valid signature from an authorized actor cannot prove (a) who approved it, (b) that they held required permissions, or (c) that the content matches what was reviewed. Absence of proof is treated as proof of ineligibility — the gate never assumes benign intent. Execution proceeds only when every check affirmatively passes; any gap, ambiguity, or failure closes the gate.