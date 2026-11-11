"""Read-only, cached bulk Smart Rebuy scan. No order submission."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock
from time import monotonic

from backend.v19_manual_crypto_rebuy_preview import preview

PAIRS = ['UNIUSD','BTCUSD','XRPUSD','SOLUSD','HYPEUSD','LDOUSD','AVAXUSD','FILUSD','LTCUSD','ARBUSD','ADAUSD','ONDOUSD','SKYUSD','SHIBUSD','LINKUSD','SUSHIUSD','BATUSD','ETHUSD','XTZUSD','AAVEUSD','DOTUSD','CRVUSD','BCHUSD','GRTUSD','PAXGUSD','DOGEUSD','BONKUSD','YFIUSD','POLUSD']
_CACHE = {"at": 0.0, "rows": None}
_LOCK = Lock()
TTL_SECONDS = 90


def scan_all(client, data_client):
    # A single in-flight scan avoids hammering Alpaca on repeated dashboard refreshes.
    with _LOCK:
        if _CACHE["rows"] is not None and monotonic() - _CACHE["at"] < TTL_SECONDS:
            return {"rows": _CACHE["rows"], "scannedAt": _CACHE["scannedAt"], "cached": True,
                    "total": len(PAIRS), "readOnly": True}
        def one(symbol):
            try:
                result = preview(client, data_client, symbol)
                return {"symbol": symbol[:-3] + "/USD", **result}
            except Exception:
                return {"symbol": symbol[:-3] + "/USD", "status": "WAIT", "readOnly": True,
                        "orderSubmitted": False, "reason": "Broker data unavailable or unverified"}
        rows = [None] * len(PAIRS)
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(one, sym): i for i, sym in enumerate(PAIRS)}
            for future in as_completed(futures):
                rows[futures[future]] = future.result()
        stamp = datetime.now(timezone.utc).isoformat()
        _CACHE.update(at=monotonic(), rows=rows, scannedAt=stamp)
        return {"rows": rows, "scannedAt": stamp, "cached": False,
                "total": len(PAIRS), "readOnly": True}
