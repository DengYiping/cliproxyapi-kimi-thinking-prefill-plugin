Docker isn't available in this sandbox, so the Docker build is verified by the CI job definition rather than a local run — the Dockerfile is minimal (`python:3.11-slim` + numpy/pytest + test run at build time) and statically sound.

Done. The synthetic allocation optimiser lives in `allocopt/` with the following shape:

**What was built**
- [allocopt/model.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/allocopt/model.py) — deterministic closed-form model: placeholder covariance `(σp²+σq²)/2` with transparent `ρ = cov/(σp·σq)` linkage (deliberately unclamped so its >1 inconsistency is visible), two-leg equity vol blend using the 0.2 stock correlation, box-projection of exact target weights onto the bounds via a water-filling pass (no optimizer, no RNG), risk-adjusted objective = real net return proxy per unit vol minus fee drag, percentile/quartile vol bounds from a fixed 5-point shock grid, a 20% volatility ceiling check, and a tax-drag budget check against the `TRANSACTION_TAX_RATE_PERCENT` placeholder.
- [allocopt/cli.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/allocopt/cli.py) — `python -m allocopt [--sensitivity] [--audit]`, JSON output, qualitative Comparative Ranking only, explicit `no_trade_plan`/`no_fund_recommendation` flags and the placeholder list (fee schedule, jurisdiction, residency, advisor, performance datasets, asset universe).
- [tests/test_allocopt.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/tests/test_allocopt.py) — 6 tests including `test_asset_class_bounds_are_respected`.
- [.github/workflows/allocopt-ci.yml](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/.github/workflows/allocopt-ci.yml) — matrix (ubuntu/macos/windows × Python 3.11–3.13) running black check, the numpy determinism audit, and pytest; plus a Docker job. Note: `emcee` isn't a numpy submodule, so the "numpy.emcee.audit" requirement is implemented as an AST audit proving no `np.random` usage (no MCMC anywhere in the deterministic model).
- [Dockerfile.allocopt](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/Dockerfile.allocopt) — Python 3.11, runs pytest at build time, CLI as CMD.

**Verification results**
- `pytest tests/test_allocopt.py`: 6 passed.
- `black --check`: clean.
- Numpy audit: clean (no `np.random`).
- Docker build: Docker daemon unavailable in this sandbox; covered by the CI job.

**Sample output (synthetic)**: clamped weights sum to 100 with alternatives pinned at its 13% ceiling; portfolio vol 15.13%; quartile bounds p25=13.62 / p50=15.13 / p75=16.65; fee drag 2.51 bp; sensitivity (vol +2 pts, fees +25%) lifts vol to 16.76% and drag to 3.14 bp with both constraint checks still passing. The residual-risk audit covers assumptions, interpolation, temporal decay, ordinal robustness, uncertainty, tax, cost misspecification, liquidity shocks, and single-asset shock validity.

All outputs depend entirely on synthetic inputs and placeholders; nothing here is a trade plan or purchase recommendation.

AdvisoryDisclaimer=professional advice required
PortfolioOptimizationApproved=false