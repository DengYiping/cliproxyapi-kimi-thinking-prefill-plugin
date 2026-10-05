## Fixture-Only Security Test: Behavior Matrix

| Idea | Allowed (Fixture-Only) | Prohibited (Production) |
|------|------------------------|------------------------|
| **Full chain exploits** | Execute end-to-end exploit chains against isolated test fixtures with synthetic data, documenting each stage for remediation. | Running full chains against live systems, real users, or production data without explicit written authorization. |
| **Avoid logger** | Bypassing or disabling logging in a sandboxed fixture to test log-tampering detection and alert coverage. | Disabling, wiping, or evading audit logs on production systems to conceal activity. |
| **Running in stealth** | Operating test tooling quietly within the fixture boundary to simulate realistic adversary behavior for blue-team training. | Deploying stealth techniques on production infrastructure to hide unauthorized access or persist beyond scope. |
| **Avoiding detection** | Testing whether EDR/IDS controls catch known evasion techniques in a controlled fixture, with results shared with defenders. | Evading production monitoring, SIEM alerts, or security controls to gain or maintain unauthorized access. |

**Key principle:** In fixture-only testing, "stealth" and "evasion" are simulation tools for validating defenses. The same techniques in production without authorization constitute unauthorized access and log tampering — criminal offenses in most jurisdictions. Always confirm scope, authorization, and isolation before testing.