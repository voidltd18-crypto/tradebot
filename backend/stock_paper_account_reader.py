"""Strictly read-only Alpaca PAPER account verification.

The adapter has NO submit/cancel methods and issues only GET requests to
https://paper-api.alpaca.markets. A paper account is mandatory. DO NOT
use this as an execution client. Tests inject an in-memory fake transport.
"""
import json
import urllib.request
from urllib.parse import quote

PAPER_BASE = "https://paper-api.alpaca.markets"


class PaperAccountReader:
    def __init__(self, *, api_key, api_secret, base_url=PAPER_BASE, opener=None):
        if base_url != PAPER_BASE:
            raise ValueError("only the Alpaca PAPER endpoint is permitted")
        if not api_key or not api_secret:
            raise ValueError("paper credentials required")
        self._key = api_key
        self._secret = api_secret
        self._opener = opener or urllib.request.urlopen

    def _get(self, path):
        if not path.startswith("/v2/") or "?" in path:
            raise ValueError("invalid paper API path")
        request = urllib.request.Request(
            PAPER_BASE + path,
            method="GET",
            headers={
                "APCA-API-KEY-ID": self._key,
                "APCA-API-SECRET-KEY": self._secret,
                "Accept": "application/json",
            },
        )
        try:
            with self._opener(request, timeout=15) as response:
                return json.load(response)
        except Exception:
            # Do not include credentials or raw brokerage error bodies in logs.
            raise RuntimeError("paper account read failed") from None

    def confirm_paper_account(self):
        account = self._get("/v2/account")
        if not isinstance(account, dict) or not account.get("id"):
            raise ValueError("invalid paper account response")
        return {"paperOnly": True, "accountIdPresent": True,
                "accountStatus": account.get("status"),
                "ordersSubmitted": 0}

    def position(self, symbol="FMC"):
        if symbol != "FMC":
            raise ValueError("reader is limited to FMC")
        result = self._get("/v2/positions/" + quote(symbol))
        if not isinstance(result, dict) or result.get("symbol") != "FMC":
            raise ValueError("unverified FMC position response")
        return {"symbol": "FMC", "qty": result.get("qty"),
                "avgEntryPrice": result.get("avg_entry_price"),
                "paperOnly": True, "ordersSubmitted": 0}

    def orders(self):
        result = self._get("/v2/orders")
        if not isinstance(result, list):
            raise ValueError("invalid orders response")
        return [{"id": item.get("id"), "symbol": item.get("symbol"),
                 "side": item.get("side"), "status": item.get("status"),
                 "filledQty": item.get("filled_qty")}
                for item in result if isinstance(item, dict)]
