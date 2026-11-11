"""Research-only comparison including days without profit exit signals.

For NO_SIGNAL, assumes a forced position liquidation at final observed bar
close, purely so returns are comparable. This is not actual TradeBot policy,
nor an executable fill or verified Alpaca position.
"""
from math import isfinite
from backend.stock_momentum_cost_model import CostAssumptions, compare_costed_exits
from backend.stock_momentum_replay import _parse_observations


def full_session_comparison(entry_price, observations, *, assumptions=None):
    if assumptions is None:
        assumptions = CostAssumptions()
    points = _parse_observations(observations)
    if len(points) < 2:
        raise ValueError("at least two bars required for a close simulation")
    result = compare_costed_exits(entry_price, observations, assumptions=assumptions)
    entry = float(entry_price)
    entry_fill = entry * (1 + (assumptions.spread_bps / 2 +
                               assumptions.entry_slippage_bps) / 10000)
    final_close = points[-1].price
    exit_fill = final_close * (1 - (assumptions.spread_bps / 2 +
                                   assumptions.exit_slippage_bps) / 10000)
    fallback_pnl = ((exit_fill - entry_fill) * assumptions.shares -
                    2 * assumptions.fee_per_side_usd)
    fallback_invested = entry_fill * assumptions.shares + assumptions.fee_per_side_usd
    forced_return = round(fallback_pnl / fallback_invested * 100, 4)

    def one(side):
        fill = result[side]
        if fill["status"] == "SIMULATED_FILL":
            return {"status": "SIMULATED_PROFIT_EXIT",
                    "netReturnPct": fill["netReturnPct"],
                    "netPnlUsd": fill["netPnlUsd"],
                    "timestamp": fill["fillTimestamp"]}
        # A missing/stale quote is NOT a safe executable close. Preserve it
        # explicitly; do not silently substitute hypothetical forced close.
        if fill["status"] not in {"NO_SIGNAL"}:
            return {"status": fill["status"], "netReturnPct": None,
                    "netPnlUsd": None, "timestamp": None}
        return {"status": "ASSUMED_LAST_BAR_LIQUIDATION",
                "netReturnPct": forced_return,
                "netPnlUsd": round(fallback_pnl, 6),
                "timestamp": points[-1].timestamp.isoformat()}
    candidate = one("candidate")
    reference = one("referenceTrailingExit")
    both_comparable = (candidate["netPnlUsd"] is not None and
                       reference["netPnlUsd"] is not None)
    return {
        "readOnly": True, "ordersSubmitted": 0, "releaseReady": False,
        "assumption": "If no signal, hypothetical liquidation at LAST observed bar close",
        "candidate": candidate, "reference": reference,
        "candidateMinusReferenceUsd": round(
            candidate["netPnlUsd"] - reference["netPnlUsd"], 6
        ) if both_comparable else None,
    }
