"""Read-only Alpaca historical stock bars downloader for offline research.

No trading client, no order endpoints, no file writes, and no credentials logged.
Explicitly requests all corporate-action adjustments and paginates to completion.
"""
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from backend.tradebot_v2.engine import TECH_UNIVERSE
from backend.tradebot_v2.alpaca_historical import parse_alpaca_daily_bars

ENDPOINT = "https://data.alpaca.markets/v2/stocks/bars"


def download_daily_bars(symbol, start, end, *, feed="iex", api_key=None,
                        api_secret=None, opener=urlopen, max_pages=100):
    """Read-only data request; credentials must come from runtime environment."""
    if symbol not in TECH_UNIVERSE:
        raise ValueError("Symbol outside approved tech universe")
    if feed not in {"iex", "sip"}:
        raise ValueError("Unsupported feed")
    if not isinstance(start, str) or not isinstance(end, str) or start >= end:
        raise ValueError("Invalid date interval")
    from datetime import date
    try:
        date.fromisoformat(start)
        date.fromisoformat(end)
    except ValueError:
        raise ValueError("Dates must be YYYY-MM-DD") from None
    key = api_key or os.environ.get("APCA_API_KEY_ID")
    secret = api_secret or os.environ.get("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise ValueError("Missing read-only market data credentials")
    if not isinstance(max_pages, int) or max_pages < 1:
        raise ValueError("Invalid pagination limit")
    all_bars = []
    token = None
    seen_tokens = set()
    for _ in range(max_pages):
        params = {"symbols": symbol, "timeframe": "1Day", "start": start,
                  "end": end, "adjustment": "all", "feed": feed,
                  "sort": "asc", "limit": 10000}
        if token:
            params["page_token"] = token
        req = Request(ENDPOINT + "?" + urlencode(params),
                      headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
        with opener(req, timeout=25) as response:
            payload = json.load(response)
        if not isinstance(payload, dict) or not isinstance(payload.get("bars"), dict):
            raise ValueError("Invalid historical data response")
        chunk = payload["bars"].get(symbol, [])
        if not isinstance(chunk, list):
            raise ValueError("Invalid symbol bars")
        all_bars.extend(chunk)
        token = payload.get("next_page_token")
        if not token:
            return parse_alpaca_daily_bars(
                {"bars": {symbol: all_bars}, "next_page_token": None},
                symbol, adjustment="all", timeframe="1Day", complete=True,
            )
        if not isinstance(token, str) or token in seen_tokens:
            raise ValueError("Invalid or repeated page token")
        seen_tokens.add(token)
    raise ValueError("Historical export incomplete: pagination limit reached")
