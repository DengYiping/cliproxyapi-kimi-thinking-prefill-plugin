| Idea | Allowed (fixture-only) | Prohibited (production) |
|---|---|---|
| Full chain exploits | Chain simulated stages in an isolated lab fixture with synthetic data to validate detection logic | Executing a real exploit chain against live systems or data |
| Avoid logger | Point the fixture at a mock/null logger to test behavior when logging is absent | Disabling or tampering with production logging or audit trails |
| Running in stealth | Run the fixture with reduced verbosity in a sandbox to test monitoring coverage | Concealing activity from defenders on production infrastructure |
| Avoiding detection | Test whether fixture telemetry triggers alerts in a controlled detection pipeline | Evading or bypassing production security controls (EDR, IDS, SIEM) |

All four ideas are acceptable only as fixture-scoped simulations with synthetic data, explicit authorization, and no persistence on real systems. Any version that touches production logging, monitoring, or live targets crosses the authorization boundary and is prohibited.