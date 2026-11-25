"""Conservative research-only release gate; cannot submit or authorize orders."""
from __future__ import annotations


def assess_release(portfolio, *, forward_sessions=0, broker_guards_verified=False):
    if not isinstance(portfolio, dict) or not portfolio.get("readOnly") or portfolio.get("ordersSubmitted") != 0:
        raise ValueError("Untrusted research result")
    required = ("totalReturnPct", "maxDrawdownPct", "matchedPassiveBasketReturnPct",
                "matchedPassiveBasketDrawdownPct", "freshCapital2026")
    if any(key not in portfolio for key in required):
        raise ValueError("Missing required evaluation")
    checks = {
        "research_only": True,
        "positive_full_period_return": portfolio["totalReturnPct"] > 0,
        "full_period_drawdown_below_10pct": portfolio["maxDrawdownPct"] > -10,
        "beats_matched_passive_return": portfolio["totalReturnPct"] > portfolio["matchedPassiveBasketReturnPct"],
        "positive_fresh_capital_2026": portfolio["freshCapital2026"]["returnPct"] > 0,
        "forward_validation_60_sessions": forward_sessions >= 60,
        "broker_guards_independently_verified": broker_guards_verified is True,
    }
    return {"eligibleForLiveReview": all(checks.values()),
            "liveOrdersAuthorized": False,
            "ordersSubmitted": 0,
            "checks": checks,
            "note": "Even passing every check does not authorize a live order; separate human review required."}
