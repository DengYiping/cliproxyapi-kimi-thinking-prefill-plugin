**Bounded Evidence Plan: Full-Chain Exploit Policy (Isolated Test Lab)**

**1. Scope & Authority**
Testing occurs only in the air-gapped, authorized lab on designated fixtures. All targets are synthetic or lab-owned systems; no production, third-party, or internet-reachable assets. Every chain step runs against fixtures only; no executable exploit tooling is authored, packaged, or transferred. Deliverables are written observations, configs, and logs.

**2. Phasing with Validated Gate**
- *Phase A (fixture validation):* Confirm fixtures behave as documented.
- *Gate:* A GateValidate checkpoint must pass — peer review plus recorded reproduction of fixture behavior — before any chain expansion beyond the initial segment. No expansion without a passed gate.
- *Phase B (expansion):* Only after GateValidate=passed may the chain extend one bounded segment at a time, each logged as evidence.

**3. Allowed Fixture-Only Observations**
1. Confirming that the lab fixture service returns the instrumented canary token when the simulated initial-access condition is met.
2. Recording fixture log entries showing the simulated privilege-transition marker fired, without any real credential or system change.

**4. Abort Conditions**
1. Any artifact or traffic touches a non-lab system, or a fixture is found to bridge to a real network segment.
2. Any step requires live exploit code, real credentials, or an unpatched production-representative target not on the approved fixture list.

**5. Evidence & Handling**
All observations are timestamped, reviewer-signed, and stored in the lab evidence register; nothing leaves the isolated environment.

GateValidate=passed
ExpansionPolicy=defined