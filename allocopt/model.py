"""Deterministic closed-form synthetic allocation model.

Synthetic market examples only. All figures are illustrative placeholders;
the fee schedule, jurisdiction, residency, advisor, performance datasets,
and asset universe are placeholders pending real (out-of-scope) data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# ---------------------------------------------------------------------------
# Governance constants (always emitted; never flipped by the model).
# ---------------------------------------------------------------------------
AdvisoryDisclaimer = "professional advice required"
PortfolioOptimizationApproved = False

# Tax placeholder: jurisdiction/residency/advisor unspecified by design.
TRANSACTION_TAX_RATE_PERCENT = 0.25  # placeholder only, not a real rate

# ---------------------------------------------------------------------------
# Synthetic inputs (percent, per annum).
# ---------------------------------------------------------------------------
ASSET_CLASSES = (
    "equities",
    "bonds",
    "treasuries",
    "commodities",
    "cash",
    "alternatives",
)

INPUTS: dict = {
    # The brief supplies two stock volatilities (25%, 18%); we model equities
    # as a transparent synthetic blend and expose both legs in the audit.
    "volatility_pct": {
        "equities": 25.0,
        "equities_leg_b": 18.0,  # second synthetic stock series
        "bonds": 8.0,
        "treasuries": 8.0,  # treasury vol placeholder = bond vol
        "commodities": 22.0,
        "cash": 2.0,
        "alternatives": 18.0,  # placeholder proxy vol
    },
    "stock_correlation": 0.2,
    # Covariance placeholder: cov(p, q) := (sigma_p^2 + sigma_q^2) / 2.
    # Deliberately naive; flagged in the residual-risk audit.
    "covariance_form": "(sigma_p^2 + sigma_q^2)/2",
    "friction_bp": {"equities": 1.75, "bonds": 0.87},
    "commodity_expense_pct_pa": 0.18,
    "inflation_pct": 3.0,
}

# Allocation bounds in percent of portfolio.
BOUNDS: dict[str, tuple[float, float]] = {
    "equities": (35.0, 54.0),
    "bonds": (2.0, 9.0),
    "treasuries": (9.0, 18.0),
    "commodities": (3.0, 12.0),
    "cash": (5.0, 13.0),
    "alternatives": (0.0, 13.0),
}

# Exact target weighting supplied by the brief's synthetic scenario. The
# optimiser projects/clamps onto the bound box; it does not "discover" a
# portfolio, so nothing here is a recommendation.
TARGET_WEIGHTS_PCT: dict[str, float] = {
    "equities": 44.0,
    "bonds": 6.0,
    "treasuries": 14.0,
    "commodities": 8.0,
    "cash": 9.0,
    "alternatives": 19.0,  # deliberately out-of-bounds to exercise clamping
}


# ---------------------------------------------------------------------------
# Covariance / correlation linkage (transparent, closed form).
# ---------------------------------------------------------------------------
def covariance_placeholder(sigma_p: float, sigma_q: float) -> float:
    """Placeholder covariance: (sigma_p^2 + sigma_q^2) / 2 (percent^2)."""
    return (sigma_p**2 + sigma_q**2) / 2.0


def correlation_from_covariance(cov: float, sigma_p: float, sigma_q: float) -> float:
    """Implied correlation rho = cov / (sigma_p * sigma_q), unclamped so the
    linkage stays transparent (and its flaws visible in the audit)."""
    return cov / (sigma_p * sigma_q)


def covariance_matrix(vols_pct: dict[str, float]) -> np.ndarray:
    """Full covariance matrix; diagonal is variance, off-diagonal uses the
    placeholder. Equities' two stock legs share the supplied 0.2 stock
    correlation before blending."""
    names = list(vols_pct)
    n = len(names)
    cov = np.zeros((n, n))
    for i, a in enumerate(names):
        for j, b in enumerate(names):
            if i == j:
                cov[i, j] = vols_pct[a] ** 2
            else:
                cov[i, j] = covariance_placeholder(vols_pct[a], vols_pct[b])
    return cov


def blended_equity_vol(vol_a: float, vol_b: float, rho: float) -> float:
    """Two synthetic stock legs (equal weight) blended with the supplied
    stock correlation; closed form, deterministic."""
    var = 0.25 * (vol_a**2 + vol_b**2) + 2.0 * 0.25 * rho * vol_a * vol_b
    return float(np.sqrt(var))


# ---------------------------------------------------------------------------
# Objective: risk-adjusted expected return minus fee drag (closed form).
# ---------------------------------------------------------------------------
def fee_drag_bp(
    weights_pct: dict[str, float], friction_bp: dict[str, float], commodity_expense_pct: float
) -> float:
    """Deterministic annualized fee drag in bp from friction costs and the
    commodity expense ratio. Cash/treasuries/alternatives: 0 bp placeholder."""
    drag = 0.0
    drag += weights_pct["equities"] * friction_bp["equities"] / 100.0
    drag += weights_pct["bonds"] * friction_bp["bonds"] / 100.0
    drag += weights_pct["commodities"] * commodity_expense_pct * 100.0 / 100.0
    return drag


def risk_adjusted_objective(
    weights_pct: dict[str, float], port_vol_pct: float, drag_bp: float, inflation_pct: float
) -> float:
    """Closed-form score: real, fee-adjusted return proxy per unit of vol.

    Expected-return proxy is synthetic: vol * 0.4 (a fixed placeholder risk
    premium ratio), minus inflation, minus fee drag. Deterministic; no
    sampling, no optimizer, no look-ahead.
    """
    expected_proxy_pct = port_vol_pct * 0.4
    real_net_pct = expected_proxy_pct - inflation_pct - drag_bp / 100.0
    if port_vol_pct <= 0:
        return 0.0
    return real_net_pct / port_vol_pct


# ---------------------------------------------------------------------------
# Constraint checks.
# ---------------------------------------------------------------------------
def check_bounds(weights_pct: dict[str, float]) -> dict[str, bool]:
    return {k: BOUNDS[k][0] - 1e-9 <= w <= BOUNDS[k][1] + 1e-9 for k, w in weights_pct.items()}


def check_volatility_constraint(port_vol_pct: float, ceiling_pct: float = 20.0) -> dict:
    """Synthetic ceiling: portfolio vol must stay under 20% pa."""
    return {
        "portfolio_vol_pct": round(port_vol_pct, 4),
        "ceiling_pct": ceiling_pct,
        "passed": port_vol_pct <= ceiling_pct,
    }


def check_tax_constraint(
    turnover_pct: float, tax_rate_pct: float = TRANSACTION_TAX_RATE_PERCENT, budget_bp: float = 50.0
) -> dict:
    """Placeholder check: estimated transaction-tax drag must stay within a
    synthetic 50 bp budget. TRANSACTION_TAX_RATE_PERCENT is a placeholder,
    not a jurisdictional rate."""
    drag_bp = turnover_pct * tax_rate_pct
    return {
        "tax_rate_placeholder_pct": tax_rate_pct,
        "turnover_pct": turnover_pct,
        "estimated_tax_drag_bp": round(drag_bp, 4),
        "budget_bp": budget_bp,
        "passed": drag_bp <= budget_bp,
    }


# ---------------------------------------------------------------------------
# Percentile / quartile bounds on portfolio volatility.
# ---------------------------------------------------------------------------
def volatility_percentiles(
    weights_pct: dict[str, float], vols_pct: dict[str, float]
) -> dict[str, float]:
    """Deterministic quartile bounds from a synthetic one-factor shock grid:
    scale all vols by factors {0.75, 0.9, 1.0, 1.1, 1.25} (fixed, no RNG) and
    report min/25/50/75/max of resulting portfolio vol."""
    factors = (0.75, 0.9, 1.0, 1.1, 1.25)
    base_w = np.array([weights_pct[k] for k in ASSET_CLASSES]) / 100.0
    samples = []
    for f in factors:
        scaled = {k: v * f for k, v in vols_pct.items()}
        cov = covariance_matrix(scaled)
        w = (
            np.array([base_w[ASSET_CLASSES.index(k)] for k in vols_pct])
            if set(vols_pct) == set(ASSET_CLASSES)
            else base_w[: len(vols_pct)]
        )
        samples.append(float(np.sqrt(w @ cov @ w)))
    qs = np.percentile(samples, [0, 25, 50, 75, 100])
    return {
        "p0": round(qs[0], 3),
        "p25": round(qs[1], 3),
        "p50": round(qs[2], 3),
        "p75": round(qs[3], 3),
        "p100": round(qs[4], 3),
    }


# ---------------------------------------------------------------------------
# Exact target weighting: clamp onto bounds, then renormalize residually.
# ---------------------------------------------------------------------------
def project_to_bounds(target_pct: dict[str, float]) -> dict[str, float]:
    """Closed-form box projection: clamp to bounds, then deterministically
    water-fill the residual across classes not pinned at a bound, repeating
    until weights sum to 100. No optimizer, no randomness."""
    w = {k: min(max(v, BOUNDS[k][0]), BOUNDS[k][1]) for k, v in target_pct.items()}
    for _ in range(len(w) + 2):
        residual = 100.0 - sum(w.values())
        if abs(residual) < 1e-9:
            break
        free = [
            k
            for k in w
            if (residual > 0 and w[k] < BOUNDS[k][1] - 1e-12)
            or (residual < 0 and w[k] > BOUNDS[k][0] + 1e-12)
        ]
        if not free:
            break
        share = residual / len(free)
        for k in free:
            w[k] = min(max(w[k] + share, BOUNDS[k][0]), BOUNDS[k][1])
    return {k: round(v, 4) for k, v in w.items()}


# ---------------------------------------------------------------------------
# Result object.
# ---------------------------------------------------------------------------
@dataclass
class AllocationResult:
    weights_pct: dict[str, float]
    portfolio_vol_pct: float
    vol_percentiles: dict[str, float]
    fee_drag_bp: float
    objective: float
    bound_checks: dict[str, bool]
    vol_check: dict
    tax_check: dict
    equity_vol_blend_pct: float
    implied_correlation_note: str
    synthetic_only: bool = True
    advisory_disclaimer: str = AdvisoryDisclaimer
    portfolio_optimization_approved: bool = PortfolioOptimizationApproved
    notes: list = field(default_factory=list)


def optimize(vol_shift_pts: float = 0.0, fee_scale: float = 1.0) -> AllocationResult:
    """Run the deterministic synthetic allocation. No trade plan is produced;
    output is a qualitative comparative ranking only."""
    vols = dict(INPUTS["volatility_pct"])
    vols = {k: v + vol_shift_pts for k, v in vols.items()}

    eq_vol = blended_equity_vol(
        vols["equities"], vols["equities_leg_b"], INPUTS["stock_correlation"]
    )
    class_vols = {
        "equities": eq_vol,
        "bonds": vols["bonds"],
        "treasuries": vols["treasuries"],
        "commodities": vols["commodities"],
        "cash": vols["cash"],
        "alternatives": vols["alternatives"],
    }

    weights = project_to_bounds(TARGET_WEIGHTS_PCT)
    w = np.array([weights[k] for k in ASSET_CLASSES]) / 100.0
    cov = covariance_matrix(class_vols)
    port_vol = float(np.sqrt(w @ cov @ w))

    friction = {k: v * fee_scale for k, v in INPUTS["friction_bp"].items()}
    commodity_exp = INPUTS["commodity_expense_pct_pa"] * fee_scale
    drag = fee_drag_bp(weights, friction, commodity_exp)
    objective = risk_adjusted_objective(weights, port_vol, drag, INPUTS["inflation_pct"])

    # Synthetic turnover proxy: half the L1 distance from target to clamped.
    turnover = 0.5 * sum(abs(weights[k] - TARGET_WEIGHTS_PCT[k]) for k in ASSET_CLASSES)

    cov_eq_bond = covariance_placeholder(class_vols["equities"], class_vols["bonds"])
    implied_rho = correlation_from_covariance(
        cov_eq_bond, class_vols["equities"], class_vols["bonds"]
    )

    return AllocationResult(
        weights_pct=weights,
        portfolio_vol_pct=round(port_vol, 4),
        vol_percentiles=volatility_percentiles(weights, class_vols),
        fee_drag_bp=round(drag, 4),
        objective=round(objective, 6),
        bound_checks=check_bounds(weights),
        vol_check=check_volatility_constraint(port_vol),
        tax_check=check_tax_constraint(round(turnover, 4)),
        equity_vol_blend_pct=round(eq_vol, 4),
        implied_correlation_note=(
            f"placeholder cov(equities,bonds)={cov_eq_bond:.2f} pct^2 implies "
            f"rho={implied_rho:.3f}; >1 exposes the placeholder's "
            f"inconsistency (see residual-risk audit)"
        ),
        notes=[
            "Synthetic inputs only; no live market data used.",
            "Closed-form deterministic objective; no optimizer or RNG.",
            "Qualitative Comparative Ranking only; no trade plan.",
        ],
    )


def sensitivity() -> dict:
    """Sensitivity: volatilities +2 points and fees +25%, per the brief."""
    base = optimize()
    shocked = optimize(vol_shift_pts=2.0, fee_scale=1.25)
    return {
        "base_objective": base.objective,
        "shocked_objective": shocked.objective,
        "delta_objective": round(shocked.objective - base.objective, 6),
        "base_vol_pct": base.portfolio_vol_pct,
        "shocked_vol_pct": shocked.portfolio_vol_pct,
        "base_fee_drag_bp": base.fee_drag_bp,
        "shocked_fee_drag_bp": shocked.fee_drag_bp,
        "shocked_vol_check_passed": shocked.vol_check["passed"],
        "shocked_tax_check_passed": shocked.tax_check["passed"],
    }


def residual_risk_audit() -> dict[str, str]:
    """Qualitative audit of residual risks; no quantitative endorsement."""
    return {
        "assumptions": "Fixed synthetic vols and a 0.4 placeholder risk-premium "
        "ratio; real regimes differ materially.",
        "interpolation": "No interpolation used; quartile bounds come from a "
        "fixed 5-point shock grid, not fitted curves.",
        "temporal_decay": "Vols are static per-annum figures; no decay or "
        "regime-switching is modelled.",
        "ordinal_robustness": "Ranking is ordinal only; small input changes "
        "(see sensitivity) can reorder outcomes.",
        "uncertainty": "Point estimates only; no confidence intervals on "
        "inputs, which are placeholders.",
        "tax": "TRANSACTION_TAX_RATE_PERCENT is a placeholder; jurisdiction, "
        "residency, and advisor specifics are undefined.",
        "cost_misspecification": "Friction costs are flat bp placeholders; "
        "spread/impact tiers are unmodelled.",
        "liquidity_shocks": "No liquidity adjustment; commodities/alternatives "
        "liquidity risk is unrepresented.",
        "single_asset_shock_validity": "The placeholder covariance can imply "
        "correlations >1, so single-asset shock "
        "responses are not guaranteed valid.",
    }


def comparative_ranking(result: AllocationResult) -> list[str]:
    """Qualitative Comparative Ranking of synthetic classes by standalone
    vol ascending. Labels only; not a recommendation."""
    return sorted(
        result.weights_pct,
        key=lambda k: INPUTS["volatility_pct"].get(k, INPUTS["volatility_pct"]["equities"]),
    )
