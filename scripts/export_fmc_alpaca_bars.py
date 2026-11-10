"""Read-only Alpaca FMC 1-minute bar export for OFFLINE TradeBot replay.

Uses market data API only; NEVER accesses trading/order endpoints.
Credentials read from local environment, never supplied as CLI flags.
"""
import argparse
import csv
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA_ENDPOINT = "https://data.alpaca.markets/v2/stocks/FMC/bars"


def _utc(text):
    if not isinstance(text, str):
        raise ValueError("start/end must be ISO-8601 timestamps")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include UTC offset")
    return parsed.astimezone(timezone.utc)


def fetch_fmc_bars(start, end, *, api_key, api_secret, feed="iex", opener=None,
                   max_bars=5000):
    """Return timestamp/close rows; read-only requests, bounded and paginated.

    Data is NOT authenticated as FMC exchange-wide data when using IEX feed:
    IEX bars only reflect eligible IEX activity.
    """
    start_dt, end_dt = _utc(start), _utc(end)
    if start_dt >= end_dt or (end_dt - start_dt).days > 30:
        raise ValueError("select a nonempty window of at most 30 days")
    if end_dt > datetime.now(timezone.utc):
        raise ValueError("end must not be in the future")
    if feed not in {"iex", "sip"}:
        raise ValueError("feed must be iex or sip")
    if not api_key or not api_secret:
        raise ValueError("Alpaca market-data credentials required in environment")
    if not 1 <= max_bars <= 5000:
        raise ValueError("max_bars must be between 1 and 5000")
    if opener is None:
        opener = urllib.request.urlopen
    rows, token, seen = [], None, set()
    for _ in range(100):
        params = {"timeframe": "1Min", "start": start_dt.isoformat(),
                  "end": end_dt.isoformat(), "limit": 1000, "feed": feed,
                  "adjustment": "raw"}
        if token:
            params["page_token"] = token
        request = urllib.request.Request(
            DATA_ENDPOINT + "?" + urllib.parse.urlencode(params),
            headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret,
                     "Accept": "application/json"},
            method="GET",
        )
        # Do not include response bodies in exceptions: provider errors can
        # contain private metadata.
        try:
            with opener(request, timeout=20) as response:
                payload = json.load(response)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise RuntimeError("FMC market-data request failed; check access/feed/date") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("bars"), list):
            raise ValueError("unexpected Alpaca bars response")
        for bar in payload["bars"]:
            if not isinstance(bar, dict) or "t" not in bar or "c" not in bar:
                raise ValueError("invalid bar")
            timestamp, price = bar["t"], bar["c"]
            parsed = _utc(timestamp)
            if not start_dt <= parsed <= end_dt or not isinstance(price, (int, float)) or isinstance(price, bool):
                raise ValueError("bar outside window or non-numeric close")
            from math import isfinite
            if not isfinite(price) or price <= 0:
                raise ValueError("invalid bar price")
            if rows and parsed <= _utc(rows[-1]["timestamp"]):
                raise ValueError("bars not in strictly chronological order")
            rows.append({"timestamp": parsed.isoformat(), "close": price})
            if len(rows) > max_bars:
                raise ValueError("too many bars: select a smaller interval")
        next_token = payload.get("next_page_token")
        if not next_token:
            if not rows:
                raise ValueError("no FMC bars returned for requested interval")
            return rows
        if not isinstance(next_token, str) or next_token in seen:
            raise ValueError("invalid or repeated paging token")
        seen.add(next_token)
        token = next_token
    raise ValueError("page limit exceeded")


def export_fmc_bars(start, end, path, *, feed="iex", env=None, opener=None):
    env = os.environ if env is None else env
    rows = fetch_fmc_bars(
        start, end, api_key=env.get("APCA_API_KEY_ID") or env.get("ALPACA_API_KEY", ""),
        api_secret=env.get("APCA_API_SECRET_KEY") or env.get("ALPACA_API_SECRET", ""),
        feed=feed, opener=opener,
    )
    path = Path(path)
    if path.exists():
        raise FileExistsError("refusing to overwrite existing data file")
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("timestamp", "close"))
        writer.writeheader()
        writer.writerows(rows)
    return {"rows": len(rows), "file": str(path), "feed": feed,
            "source": "Alpaca 1-minute FMC bar closes, raw adjustment",
            "tradesSubmitted": 0}


def main():
    parser = argparse.ArgumentParser(description="Export FMC historical market-data bars ONLY")
    parser.add_argument("--start", required=True, help="ISO-8601 with offset")
    parser.add_argument("--end", required=True, help="ISO-8601 with offset")
    parser.add_argument("--out", required=True)
    parser.add_argument("--feed", choices=["iex", "sip"], default="iex")
    args = parser.parse_args()
    print(json.dumps(export_fmc_bars(args.start, args.end, args.out, feed=args.feed), indent=2))


if __name__ == "__main__":
    main()
