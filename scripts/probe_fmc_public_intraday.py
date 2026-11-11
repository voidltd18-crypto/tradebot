"""Best-effort, no-credentials public FMC intraday evidence probe.

Yahoo chart responses are unofficial market-data observations, not Alpaca
executions. Fail closed on missing timestamps, insufficient bars, or stale
responses. Never submits orders and never asserts deployment readiness.
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone
from math import isfinite

from backend.stock_momentum_cost_model import compare_costed_exits

URL = "https://query1.finance.yahoo.com/v8/finance/chart/FMC?interval=1m&range=5d"


def get_intraday_fmc(*, opener=None, session="2026-11-09"):
    opener = opener or urllib.request.urlopen
    request = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0",
                                                   "Accept": "application/json"},
                                     method="GET")
    try:
        with opener(request, timeout=20) as response:
            payload = json.load(response)
    except Exception:
        raise RuntimeError("public FMC minute chart unavailable") from None
    try:
        chart = payload["chart"]
        item = chart["result"][0]
        meta = item["meta"]
        times = item["timestamp"]
        quotes = item["indicators"]["quote"][0]["close"]
        if meta["symbol"] != "FMC" or len(times) != len(quotes):
            raise ValueError("invalid chart identity or lengths")
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError("invalid public chart response") from None
    rows = []
    for timestamp, close in zip(times, quotes):
        if close is None:
            continue
        stamp = datetime.fromtimestamp(int(timestamp), timezone.utc)
        if stamp.date().isoformat() != session:
            continue
        price = float(close)
        if not isfinite(price) or price <= 0:
            raise ValueError("invalid public price")
        if rows and stamp <= datetime.fromisoformat(rows[-1]["timestamp"]):
            raise ValueError("non-chronological minute bars")
        rows.append({"timestamp": stamp.isoformat(), "price": price})
    if len(rows) < 30:
        raise ValueError("insufficient verified-timestamp intraday bars for session")
    return rows


def main():
    bars = get_intraday_fmc()
    # The historical entry is illustrative only: not broker position evidence.
    outcome = compare_costed_exits(5.485, bars)
    result = {
        "symbol": "FMC",
        "source": "unofficial Yahoo minute close chart; unverified execution feed",
        "session": "2026-11-09", "barCount": len(bars),
        "firstTime": bars[0]["timestamp"],
        "lastTime": bars[-1]["timestamp"],
        "candidate": outcome["candidate"],
        "reference": outcome["referenceTrailingExit"],
        "simulatedDeltaUsd": outcome["candidateMinusReferenceNetPnlUsd"],
        "approvedForLive": False, "paperOrdersPlaced": 0, "liveOrdersPlaced": 0,
        "caution": "Position entry timing unknown, sampled close prices only",
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
