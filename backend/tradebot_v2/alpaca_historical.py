"""Offline parser for Alpaca v2 historical daily bar exports.

The caller must explicitly record that /v2/stocks/bars was requested with
timeframe=1Day and adjustment=all. This module NEVER calls Alpaca or a broker.
"""
from datetime import datetime
from math import isfinite

from backend.tradebot_v2.backtest import DatedClose, evaluate_out_of_sample
from backend.tradebot_v2.engine import TECH_UNIVERSE


def parse_alpaca_daily_bars(payload: dict, symbol: str, *, adjustment: str,
                            timeframe: str, complete: bool = True) -> list[DatedClose]:
    if symbol not in TECH_UNIVERSE:
        raise ValueError("Unapproved symbol")
    if adjustment != "all" or timeframe != "1Day":
        raise ValueError("Fully adjusted daily bars required")
    if not complete or not isinstance(payload, dict) or payload.get("next_page_token"):
        raise ValueError("Historical export must include every page")
    bars = payload.get("bars")
    if not isinstance(bars, dict) or not isinstance(bars.get(symbol), list):
        raise ValueError("Missing symbol bars")
    result = []
    for bar in bars[symbol]:
        if not isinstance(bar, dict):
            raise ValueError("Invalid bar")
        try:
            timestamp = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
            close = bar["c"]
        except (KeyError, AttributeError, ValueError, TypeError):
            raise ValueError("Invalid bar date or close") from None
        if timestamp.tzinfo is None or not isinstance(close, (int, float)) or isinstance(close, bool) or not isfinite(close) or close <= 0:
            raise ValueError("Invalid adjusted daily bar")
        day = timestamp.date()
        if result and day <= result[-1].day:
            raise ValueError("Bars must be strictly increasing and unique")
        result.append(DatedClose(day, float(close)))
    if not result:
        raise ValueError("Empty historical export")
    return result


def evaluate_alpaca_export(symbol: str, payload: dict, *, training_end,
                           adjustment="all", timeframe="1Day", complete=True,
                           roundtrip_fee_bps=20.0):
    rows = parse_alpaca_daily_bars(payload, symbol, adjustment=adjustment,
                                   timeframe=timeframe, complete=complete)
    return evaluate_out_of_sample(
        symbol, rows,
        source="Alpaca historical stock bars v2; adjustment=all; timeframe=1Day; externally supplied export",
        training_end=training_end, roundtrip_fee_bps=roundtrip_fee_bps,
    )
