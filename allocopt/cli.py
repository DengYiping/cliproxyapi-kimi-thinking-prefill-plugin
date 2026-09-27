"""CLI for the synthetic allocation optimiser. Educational output only."""

from __future__ import annotations

import argparse
import json

from .model import (
    AdvisoryDisclaimer,
    PortfolioOptimizationApproved,
    comparative_ranking,
    optimize,
    residual_risk_audit,
    sensitivity,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="allocopt",
        description=(
            "Hypothetical allocation optimiser on synthetic inputs. "
            "Not financial, tax, fiduciary, or brokerage advice; no "
            "executable trade plan; no fund purchase recommendation."
        ),
    )
    parser.add_argument(
        "--sensitivity", action="store_true", help="run the +2pt vol / +25% fee sensitivity"
    )
    parser.add_argument("--audit", action="store_true", help="print the residual-risk audit")
    args = parser.parse_args(argv)

    result = optimize()
    payload = {
        "synthetic_inputs_only": True,
        "weights_pct": result.weights_pct,
        "portfolio_vol_pct": result.portfolio_vol_pct,
        "vol_percentile_quartile_bounds": result.vol_percentiles,
        "fee_drag_bp": result.fee_drag_bp,
        "risk_adjusted_objective": result.objective,
        "equity_vol_blend_pct": result.equity_vol_blend_pct,
        "covariance_correlation_linkage": result.implied_correlation_note,
        "bound_checks": result.bound_checks,
        "volatility_constraint": result.vol_check,
        "tax_constraint_placeholder": result.tax_check,
        "comparative_ranking_qualitative_only": comparative_ranking(result),
        "no_trade_plan": True,
        "no_fund_recommendation": True,
        "placeholders": [
            "fee schedule",
            "jurisdiction",
            "residency",
            "advisor",
            "performance datasets",
            "asset universe",
        ],
    }
    if args.sensitivity:
        payload["sensitivity_vol_plus_2pt_fees_plus_25pct"] = sensitivity()
    if args.audit:
        payload["residual_risk_audit"] = residual_risk_audit()
    payload["AdvisoryDisclaimer"] = AdvisoryDisclaimer
    payload["PortfolioOptimizationApproved"] = PortfolioOptimizationApproved

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
