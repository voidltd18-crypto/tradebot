"""Broker-backed read-only manual rebuy preview; no order submission."""
from datetime import datetime, timezone
from backend.v19_manual_crypto_rebuy_signal import assess_manual_rebuy

def preview(client, data_client, symbol):
    sym = str(symbol or "").upper().replace("/", "")
    blocked = {"status": "WAIT", "readOnly": True, "orderSubmitted": False}
    if not (sym.endswith("USD") and sym[:-3].isalpha() and 2 <= len(sym[:-3]) <= 10):
        return {**blocked, "reason": "Invalid USD crypto symbol"}
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.data.requests import CryptoLatestQuoteRequest
        orders = client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=500))
        def matching(o):
            return (str(getattr(o, "symbol", "")).upper().replace("/", "") == sym
                    and str(getattr(o, "side", "")).lower().split(".")[-1] == "sell"
                    and str(getattr(o, "status", "")).lower().split(".")[-1] == "filled"
                    and getattr(o, "filled_at", None) is not None
                    and getattr(o, "filled_avg_price", None) is not None)
        sales = [o for o in orders if matching(o)]
        if not sales:
            return {**blocked, "reason": "No broker-confirmed filled sell found"}
        latest = max(sales, key=lambda o: o.filled_at)
        positions = client.get_all_positions()
        pending = client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500))
        pair = sym[:-3] + "/USD"
        quotes = data_client.get_crypto_latest_quote(CryptoLatestQuoteRequest(symbol_or_symbols=pair))
        quote = quotes.get(pair) if isinstance(quotes, dict) else None
        stamp = getattr(quote, "timestamp", None)
        now = datetime.now(timezone.utc)
        fresh = (isinstance(stamp, datetime) and stamp.tzinfo is not None
                 and 0 <= (now - stamp).total_seconds() <= 30)
        return {**assess_manual_rebuy(
            last_filled_sell_price=latest.filled_avg_price,
            current_ask=getattr(quote, "ask_price", None),
            sell_verified=True, quote_fresh=fresh,
            recovery_confirmed=False,  # Never infer reversal from a single quote.
            position_open=any(str(getattr(p, "symbol", "")).upper().replace("/", "") == sym for p in positions),
            order_pending=any(str(getattr(o, "symbol", "")).upper().replace("/", "") == sym for o in pending),
        ), "symbol": pair, "referenceSaleAt": latest.filled_at.isoformat(),
            "recoveryVerified": False}
    except Exception:
        return {**blocked, "reason": "Broker data unavailable or unverified"}
