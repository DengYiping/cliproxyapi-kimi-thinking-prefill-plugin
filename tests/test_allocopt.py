"""Tests for the synthetic allocation optimiser (no live data anywhere)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from allocopt import (  # noqa: E402
    AdvisoryDisclaimer,
    BOUNDS,
    PortfolioOptimizationApproved,
    optimize,
    residual_risk_audit,
    sensitivity,
)
from allocopt.cli import main  # noqa: E402


def test_asset_class_bounds_are_respected():
    result = optimize()
    for asset, (lo, hi) in BOUNDS.items():
        w = result.weights_pct[asset]
        assert lo - 1e-9 <= w <= hi + 1e-9, f"{asset}={w} outside [{lo},{hi}]"
        assert result.bound_checks[asset]
    assert abs(sum(result.weights_pct.values()) - 100.0) < 1e-6


def test_out_of_bounds_target_is_clamped():
    # Target alternatives weight (19%) exceeds the 13% ceiling by design.
    assert optimize().weights_pct["alternatives"] <= BOUNDS["alternatives"][1]


def test_governance_constants_hold():
    assert AdvisoryDisclaimer == "professional advice required"
    assert PortfolioOptimizationApproved is False


def test_sensitivity_shocks_raise_vol_and_drag():
    s = sensitivity()
    assert s["shocked_vol_pct"] > s["base_vol_pct"]
    assert s["shocked_fee_drag_bp"] > s["base_fee_drag_bp"]


def test_audit_covers_required_categories():
    required = {
        "assumptions",
        "interpolation",
        "temporal_decay",
        "ordinal_robustness",
        "uncertainty",
        "tax",
        "cost_misspecification",
        "liquidity_shocks",
        "single_asset_shock_validity",
    }
    assert required <= set(residual_risk_audit())


def test_cli_runs_and_discloses(capsys):
    assert main(["--sensitivity", "--audit"]) == 0
    out = capsys.readouterr().out
    assert "professional advice required" in out
    assert '"synthetic_inputs_only": true' in out
    assert '"PortfolioOptimizationApproved": false' in out
