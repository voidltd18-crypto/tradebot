"""Read-only Alpaca FMC evidence run, with strictly PAPER credentials.

No POST, PATCH or DELETE operations. No positions opened or closed.
Intended for manual GitHub workflow dispatch with dedicated PAPER secrets.
"""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from backend.stock_momentum_cost_model import compare_costed_exits
from backend.stock_paper_account_reader import PaperAccountReader
from scripts.export_fmc_alpaca_bars import fetch_fmc_bars


def _format_bars(bars):
    return [{"timestamp": bar["timestamp"], "price": bar["close"]} for bar in bars]


def check_paper_and_history(*, start, end, entry_price, feed="iex", environ=None,
                            paper_opener=None, history_opener=None):
    env = os.environ if environ is None else environ
    key = env.get("PAPER_ALPACA_API_KEY", "")
    secret = env.get("PAPER_ALPACA_SECRET_KEY", "")
    if not key or not secret:
        raise ValueError("dedicated PAPER_ALPACA_API_KEY/SECRET_KEY required")
    paper = PaperAccountReader(api_key=key, api_secret=secret, opener=paper_opener)
    account = paper.confirm_paper_account()
    # Only request data after successful PAPER endpoint verification.
    bars = fetch_fmc_bars(start, end, api_key=key, api_secret=secret,
                          feed=feed, opener=history_opener)
    comparison = compare_costed_exits(entry_price, _format_bars(bars))
    return {
        "symbol": "FMC", "source": "Alpaca authenticated historical stock bars",
        "feed": feed, "dataCount": len(bars),
        "windowStart": bars[0]["timestamp"], "windowEnd": bars[-1]["timestamp"],
        "paperEndpointVerified": account["paperOnly"],
        "paperAccountStatus": account["accountStatus"],
        "candidate": comparison["candidate"],
        "reference": comparison["referenceTrailingExit"],
        "netPnlDifferenceUsdPerShare": comparison["candidateMinusReferenceNetPnlUsd"],
        "paperOrderSubmitted": False, "liveOrderSubmitted": False,
        "releaseReady": False,
        "limitations": [
            "Hypothetical entry supplied; not a verified original FMC fill",
            "Bar closes are not executable bids/asks and omit intrabar reversals",
            "GET-only paper account verification, not paper order execution",
            "No comparison to every existing TradeBot live sell rule",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--entry-price", required=True, type=float)
    parser.add_argument("--feed", choices=["iex", "sip"], default="iex")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    # Never print secrets or raw paper account details.
    result = check_paper_and_history(
        start=args.start, end=args.end,
        entry_price=args.entry_price, feed=args.feed,
    )
    # Output is public simulation metadata, no account numbers, no positions.
    if args.out.exists():
        raise FileExistsError("refusing to overwrite report")
    with args.out.open("x", encoding="utf-8") as file:
        json.dump(result, file, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
