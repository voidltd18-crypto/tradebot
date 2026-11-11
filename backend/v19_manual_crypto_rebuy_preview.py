"""Broker-backed read-only manual rebuy preview; no order submission."""
from datetime import datetime, timezone, timedelta
from backend.v19_manual_crypto_rebuy_signal import assess_manual_rebuy
from backend.v19_manual_crypto_recovery import confirmed_recovery

def preview(client, data_client, symbol, *, broker_snapshot=None):
    sym = str(symbol or "").upper().replace("/", "")
    blocked = {"status": "WAIT", "readOnly": True, "orderSubmitted": False}
    if not (sym.endswith("USD") and sym[:-3].isalpha() and 2 <= len(sym[:-3]) <= 10):
        return {**blocked, "reason": "Invalid USD crypto symbol"}
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.data.requests import CryptoLatestQuoteRequest, CryptoBarsRequest
        from alpaca.data.timeframe import TimeFrame
        orders = (broker_snapshot["closed_orders"] if broker_snapshot is not None else
                  client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=500)))
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
        positions = (broker_snapshot["positions"] if broker_snapshot is not None else client.get_all_positions())
        pending = (broker_snapshot["open_orders"] if broker_snapshot is not None else
                   client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500)))
        pair = sym[:-3] + "/USD"
        quotes = data_client.get_crypto_latest_quote(CryptoLatestQuoteRequest(symbol_or_symbols=pair))
        quote_data = quotes if isinstance(quotes, dict) else getattr(quotes, "data", {})
        quote = quote_data.get(pair) if isinstance(quote_data, dict) else None
        stamp = getattr(quote, "timestamp", None)
        now = datetime.now(timezone.utc)
        fresh = (isinstance(stamp, datetime) and stamp.tzinfo is not None
                 and 0 <= (now - stamp).total_seconds() <= 30)
        bars_result = data_client.get_crypto_bars(CryptoBarsRequest(
            symbol_or_symbols=pair, timeframe=TimeFrame.Minute,
            start=now.replace(second=0, microsecond=0) - timedelta(minutes=45),
            end=now,
        ))
        # Aggregate only complete, consecutive 5-minute buckets.
        recovery = False
        bar_data = bars_result if isinstance(bars_result, dict) else getattr(bars_result, 'data', {})
        raw_bars = bar_data.get(pair, []) if isinstance(bar_data, dict) else []
        if raw_bars:
            from types import SimpleNamespace
            buckets = {}
            for bar in raw_bars:
                t = bar.timestamp.astimezone(timezone.utc)
                start = t.replace(minute=t.minute - t.minute % 5, second=0, microsecond=0)
                buckets.setdefault(start, []).append(bar)
            grouped = []
            for start, group in sorted(buckets.items()):
                group.sort(key=lambda x: x.timestamp)
                if len(group) == 5 and all(group[i].timestamp.astimezone(timezone.utc) == start + timedelta(minutes=i) for i in range(5)):
                    grouped.append(SimpleNamespace(timestamp=start, close=group[-1].close,
                        low=min(x.low for x in group), high=max(x.high for x in group)))
            recovery = confirmed_recovery(grouped, now=now)
        result = assess_manual_rebuy(
            last_filled_sell_price=latest.filled_avg_price,
            current_ask=getattr(quote, "ask_price", None),
            sell_verified=True, quote_fresh=fresh,
            recovery_confirmed=recovery,
            position_open=any(str(getattr(p, "symbol", "")).upper().replace("/", "") == sym for p in positions),
            order_pending=any(str(getattr(o, "symbol", "")).upper().replace("/", "") == sym for o in pending),
        )
        return {**result, "symbol": pair, "referenceSaleAt": latest.filled_at.isoformat(),
                "recoveryVerified": recovery, "quoteFresh": fresh,
                "quoteAgeSeconds": round((now - stamp).total_seconds(), 1) if isinstance(stamp, datetime) and stamp.tzinfo is not None else None,
                "quoteTimestamp": stamp.isoformat() if isinstance(stamp, datetime) else None,
                "quoteAvailable": quote is not None}
    except Exception:
        return {**blocked, "reason": "Broker data unavailable or unverified"}
