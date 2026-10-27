"""Paper-only Alpaca crypto broker preflight. No trades are submitted.

Usage:
    APCA_API_KEY_ID=... APCA_API_SECRET_KEY=... python scripts/verify_crypto_paper_preflight.py

Refuses live credentials by enforcing paper=True and checking the broker account.
"""
import json
import os
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus, TimeInForce
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoLatestQuoteRequest

SYMBOLS = ["UNI/USD", "XRP/USD", "BTC/USD"]
def main():
    key, secret = os.getenv("APCA_API_KEY_ID"), os.getenv("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise SystemExit("PAPER PREFLIGHT BLOCKED: paper API credentials missing")
    client = TradingClient(key, secret, paper=True)
    account = client.get_account()
    if str(getattr(account, "status", "")).upper().split(".")[-1] != "ACTIVE":
        raise SystemExit("PAPER PREFLIGHT BLOCKED: broker account inactive")
    # Read only: no submit_order, no cancellation and no changes to live state.
    positions = client.get_all_positions()
    pending = client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500))
    data = CryptoHistoricalDataClient(key, secret)
    verified = {}
    for pair in SYMBOLS:
        asset = client.get_asset(pair)
        asset_class = str(getattr(asset, "asset_class", "")).lower()
        quotes = data.get_crypto_latest_quote(CryptoLatestQuoteRequest(symbol_or_symbols=pair))
        quote = quotes.get(pair) if isinstance(quotes, dict) else None
        verified[pair] = {
            "assetIsCrypto": "crypto" in asset_class,
            "tradable": bool(getattr(asset, "tradable", False)),
            "freshQuotePresent": quote is not None and getattr(quote, "timestamp", None) is not None,
        }
    print(json.dumps({
        "paperClient": True,
        "accountActive": True,
        "marketOrderCryptoTif": str(TimeInForce.GTC),
        "openPositionSymbols": [str(getattr(p, "symbol", "")) for p in positions],
        "pendingOrderCount": len(pending),
        "pairs": verified,
        "ordersSubmitted": 0
    }, indent=2))
if __name__ == "__main__":
    main()
