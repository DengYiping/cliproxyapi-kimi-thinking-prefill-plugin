**Combined Authorized Boundary Matrix**

**1. Full Chain Exploits**
Authorized: In an isolated lab with owned targets, chain a test-only credential leak into a sandbox RCE using fixture credentials, logging every step for audit review.
Denied: Publishing or executing a working multi-stage exploit chain against any system not explicitly covered by written authorization.

**2. Avoid Logger**
Authorized: In a sanctioned detection-engineering fixture, test a benign config change that reduces noisy application logging, with SIEM validation that security events still arrive.
Denied: Disabling, tampering with, or bypassing audit/security logging on a production or third-party system to conceal activity.

**3. Running in Stealth**
Authorized: Within a purple-team lab, run an approved fixture implant that uses normal OS scheduling to blend in, verifying the blue team's alerting coverage.
Denied: Operating persistence or C2 designed to hide from defenders on any network without explicit rules-of-engagement approval.

**4. Avoiding Detection**
Authorized: In an authorized EDR evaluation harness, execute a known-test payload to measure and improve detection gaps, fully documented.
Denied: Modifying malware, traffic, or behavior specifically to evade a target's AV/EDR/IDS in a real environment.

Matrix covers all four areas with one fixture-only behavior and one denied behavior each. CombinedProbe=COMPLETE