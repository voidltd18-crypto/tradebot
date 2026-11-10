"""Timestamped, deterministic stock exit shadow replay.

Pure diagnostics only: no account access, no orders, and no live worker.
All timestamps must contain explicit UTC offsets. Historical samples are
sequential; no look-ahead. Observation gaps reset momentum detection.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Sequence

from backend.stock_momentum_exit_shadow import ExitSettings


@dataclass(frozen=True)
class PriceObservation:
    timestamp: datetime
    price: float


def _parse_observations(rows: Sequence[dict]) -> list[PriceObservation]:
    if not isinstance(rows, (list, tuple)) or not 1 <= len(rows) <= 5000:
        raise ValueError("provide between 1 and 5000 observations")
    parsed = []
    for row in rows:
        if not isinstance(row, dict) or "timestamp" not in row or "price" not in row:
            raise ValueError("each observation needs timestamp and price")
        raw = row["timestamp"]
        try:
            stamp = (datetime.fromisoformat(raw.replace("Z", "+00:00"))
                     if isinstance(raw, str) else raw)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("timestamps require timezone offset")
            price = float(row["price"])
        except (TypeError, ValueError, OverflowError, AttributeError) as exc:
            raise ValueError("invalid timestamp or price") from exc
        if not isfinite(price) or price <= 0:
            raise ValueError("prices must be finite and positive")
        if parsed and stamp <= parsed[-1].timestamp:
            raise ValueError("timestamps must be strictly increasing")
        parsed.append(PriceObservation(stamp, price))
    return parsed


def replay_stock_exits(
    entry_price: float,
    observations: Sequence[dict],
    *,
    settings: ExitSettings = ExitSettings(),
    sample_max_gap_seconds: int = 120,
) -> dict:
    """Replay hypothetical closes at first observed trigger, before fees/slippage.

    baseline: 0.7% trailing giveback after 2% peak gain.
    candidate: tighter 0.5% trail only after observed fast rise and >=2% peak.
    Does not imply an executable order or safe live activation.
    """
    try:
        entry = float(entry_price)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid entry price") from exc
    if not isfinite(entry) or entry <= 0:
        raise ValueError("invalid entry price")
    if sample_max_gap_seconds <= 0 or sample_max_gap_seconds > 3600:
        raise ValueError("invalid maximum gap")
    points = _parse_observations(observations)
    peak = entry
    mode = "TREND"
    streak = []
    first_candidate = None
    first_baseline = None
    events = []
    activation = settings.spike_min_gain_pct
    for idx, point in enumerate(points):
        if streak and (point.timestamp - streak[-1].timestamp).total_seconds() > sample_max_gap_seconds:
            streak = []
            mode = "TREND"  # do not carry spike evidence across stale quote gaps
        streak.append(point)
        if len(streak) > settings.spike_window:
            streak.pop(0)
        peak = max(peak, point.price)
        profit = (point.price / entry - 1) * 100
        peak_gain = (peak / entry - 1) * 100
        reversal = (1 - point.price / peak) * 100
        rise = ((point.price / streak[0].price - 1) * 100
                if len(streak) >= settings.spike_window else None)
        if (rise is not None and rise >= settings.spike_window_rise_pct and
                peak_gain >= activation):
            mode = "SPIKE"  # latch during uninterrupted observations
        armed = (peak_gain >= activation and profit > 0 and
                 len(streak) >= settings.spike_window)
        candidate_trigger = armed and reversal >= (
            settings.spike_trail_pct if mode == "SPIKE" else settings.trend_trail_pct
        )
        baseline_trigger = armed and reversal >= settings.trend_trail_pct
        record = {
            "timestamp": point.timestamp.isoformat(), "price": point.price,
            "mode": mode, "profitPct": round(profit, 4),
            "peakDrawdownPct": round(reversal, 4),
            "candidateTrigger": bool(candidate_trigger),
            "baselineTrigger": bool(baseline_trigger),
        }
        events.append(record)
        if candidate_trigger and first_candidate is None:
            first_candidate = record
        if baseline_trigger and first_baseline is None:
            first_baseline = record
    return {
        "readOnly": True, "ordersSubmitted": 0, "source": "provided_observations",
        "sampleCount": len(points), "enabledForLiveTrading": False,
        "assumptions": "first observed trigger fill at sample price; no spread, slippage, fees or PDT constraints",
        "candidateFirstExit": first_candidate,
        "baselineFirstExit": first_baseline,
        "candidateReturnPct": first_candidate["profitPct"] if first_candidate else None,
        "baselineReturnPct": first_baseline["profitPct"] if first_baseline else None,
        "events": events,
    }
