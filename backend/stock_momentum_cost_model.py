"""Conservative, deterministic execution-cost overlay for shadow replays.

No broker connection. Trigger at tick t can only fill at tick t+1, and
only if quote age is within the allowed interval. Numbers are assumptions,
not historical observed execution quotes.
"""
from dataclasses import dataclass
from math import isfinite

from backend.stock_momentum_replay import _parse_observations, replay_stock_exits


@dataclass(frozen=True)
class CostAssumptions:
    spread_bps: float = 20.0
    exit_slippage_bps: float = 15.0
    entry_slippage_bps: float = 0.0
    fee_per_side_usd: float = 0.0
    shares: float = 1.0
    max_fill_delay_seconds: int = 120

    def __post_init__(self):
        numeric = (self.spread_bps, self.exit_slippage_bps,
                   self.entry_slippage_bps, self.fee_per_side_usd, self.shares)
        if not all(isfinite(x) for x in numeric):
            raise ValueError("cost assumptions must be finite")
        if any(x < 0 for x in numeric[:-1]) or self.shares <= 0:
            raise ValueError("costs must be nonnegative and shares positive")
        if self.spread_bps > 10000 or self.exit_slippage_bps > 10000:
            raise ValueError("unreasonable spread or slippage")
        if not 1 <= self.max_fill_delay_seconds <= 3600:
            raise ValueError("invalid fill delay")


def _fill_for_signal(signal, points, assumptions, entry):
    if signal is None:
        return {"status": "NO_SIGNAL", "netPnlUsd": None, "netReturnPct": None}
    trigger_index = next(
        i for i, p in enumerate(points)
        if p.timestamp.isoformat() == signal["timestamp"]
    )
    if trigger_index + 1 >= len(points):
        return {"status": "NO_NEXT_QUOTE", "netPnlUsd": None, "netReturnPct": None,
                "triggerTimestamp": signal["timestamp"]}
    next_tick = points[trigger_index + 1]
    age = (next_tick.timestamp - points[trigger_index].timestamp).total_seconds()
    if age > assumptions.max_fill_delay_seconds:
        return {"status": "STALE_NEXT_QUOTE", "netPnlUsd": None,
                "netReturnPct": None, "triggerTimestamp": signal["timestamp"]}
    entry_fill = entry * (1 + (assumptions.spread_bps / 2 +
                               assumptions.entry_slippage_bps) / 10000)
    exit_fill = next_tick.price * (1 - (assumptions.spread_bps / 2 +
                                       assumptions.exit_slippage_bps) / 10000)
    pnl = ((exit_fill - entry_fill) * assumptions.shares -
           2 * assumptions.fee_per_side_usd)
    invested = entry_fill * assumptions.shares + assumptions.fee_per_side_usd
    return {
        "status": "SIMULATED_FILL", "triggerTimestamp": signal["timestamp"],
        "fillTimestamp": next_tick.timestamp.isoformat(),
        "triggerPrice": signal["price"], "nextObservedPrice": next_tick.price,
        "estimatedEntryFill": round(entry_fill, 6),
        "estimatedExitFill": round(exit_fill, 6),
        "netPnlUsd": round(pnl, 6),
        "netReturnPct": round(pnl / invested * 100, 4),
    }


def compare_costed_exits(entry_price, observations, *, assumptions=None,
                         reference_activation_pct=None):
    """Compare both strategies under the SAME cost and tick-delay assumptions."""
    if assumptions is None:
        assumptions = CostAssumptions()
    replay = replay_stock_exits(entry_price, observations,
                               reference_activation_pct=reference_activation_pct)
    points = _parse_observations(observations)
    baseline = _fill_for_signal(replay["baselineFirstExit"], points,
                                assumptions, float(entry_price))
    candidate = _fill_for_signal(replay["candidateFirstExit"], points,
                                 assumptions, float(entry_price))
    delta = (round(candidate["netPnlUsd"] - baseline["netPnlUsd"], 6)
             if candidate["netPnlUsd"] is not None and
                baseline["netPnlUsd"] is not None else None)
    return {
        "readOnly": True, "ordersSubmitted": 0, "enabledForLiveTrading": False,
        "source": "caller_supplied_observations",
        "dataVerifiedAsFmcHistory": False,
        "executionModel": "next observed tick; sell at adverse half-spread and slip",
        "costAssumptions": assumptions.__dict__,
        "referenceActivationPct": replay["referenceActivationPct"],
        "candidate": candidate, "referenceTrailingExit": baseline,
        "candidateMinusReferenceNetPnlUsd": delta,
        "note": "0.7% reference is a hypothetical comparator, not a verified full TradeBot strategy",
    }
