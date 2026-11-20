"""Run read-only historical research across the approved tech universe.

Usage:
  python -m backend.tradebot_v2.historical_report

Requires APCA_API_KEY_ID and APCA_API_SECRET_KEY in the environment.
Never sends orders. Fails the whole report if any symbol is incomplete.
"""
import json
from dataclasses import asdict
from datetime import date

from backend.tradebot_v2.backtest import evaluate_out_of_sample
from backend.tradebot_v2.historical_download import download_daily_bars

SYMBOLS = ("AAPL", "MSFT", "NVDA", "AMZN", "GOOG", "GOOGL", "META")
START = "2022-01-01"
END = "2026-11-19"
TRAINING_END = date(2024, 12, 31)


def build_report(*, downloader=download_daily_bars):
    results = []
    for symbol in SYMBOLS:
        rows = downloader(symbol, START, END, feed="iex")
        result = evaluate_out_of_sample(
            symbol, rows,
            source="Alpaca stock bars v2; IEX feed; adjustment=all; 1Day; "
                   f"requested {START} to {END}",
            training_end=TRAINING_END,
            roundtrip_fee_bps=20.0,
        )
        results.append(asdict(result))
    return {
        "execution_enabled": False,
        "orders_submitted": 0,
        "method": "Fixed five-bar signal outcomes; overlapping signals; "
                  "NOT a portfolio backtest or evidence of live profitability",
        "data_caveats": [
            "IEX-only data may differ from consolidated SIP market data",
            "Historical adjusted close is not a realistically executable entry price",
            "Spread, slippage, financing, taxes and market impact excluded",
            "No portfolio-level position limits or capital allocation modelled",
            "Training cutoff fixed at 2024-12-31; 2025-2026 held out",
        ],
        "results": results,
    }


def main():
    # Do not emit partial results: a missing symbol invalidates the report.
    report = build_report()
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
