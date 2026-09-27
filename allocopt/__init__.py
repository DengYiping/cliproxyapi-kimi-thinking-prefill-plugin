"""Synthetic, hypothetical allocation optimiser (educational only).

This module is NOT personalized financial, fiduciary, tax, or brokerage
advice. It produces no executable trade plan and no fund purchase
recommendation. All inputs are synthetic placeholders.
"""

from .model import (
    ASSET_CLASSES,
    BOUNDS,
    INPUTS,
    TRANSACTION_TAX_RATE_PERCENT,
    AllocationResult,
    AdvisoryDisclaimer,
    PortfolioOptimizationApproved,
    optimize,
    sensitivity,
    residual_risk_audit,
)

__all__ = [
    "ASSET_CLASSES",
    "BOUNDS",
    "INPUTS",
    "TRANSACTION_TAX_RATE_PERCENT",
    "AllocationResult",
    "AdvisoryDisclaimer",
    "PortfolioOptimizationApproved",
    "optimize",
    "sensitivity",
    "residual_risk_audit",
]
