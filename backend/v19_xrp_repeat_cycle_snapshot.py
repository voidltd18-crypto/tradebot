"""Read-only Alpaca XRP dip cycle diagnostic.

No broker order submission. Fails closed if the last filled XRP sale or fresh
ask is unverified. Spend is operator-configured. ALL uses conservative verified cash, with fee headroom.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from backend.v19_xrp_repeat_cycle import assess_xrp_dip_entry
from backend.v19_reports_crypto_rebuy import available_crypto_cash


def _sym(value):
    return str(value or "").upper().replace("/", "")


def _filled_sell(orders):
    candidates = []
    for order in orders:
        if _sym(getattr(order, "symbol", None)) != "XRPUSD":
            continue
        if str(getattr(order, "side", "")).lower().split(".")[-1] != "sell":
            continue
        if str(getattr(order, "status", "")).lower().split(".")[-1] != "filled":
            continue
        price = getattr(order, "filled_avg_price", None)
        stamp = getattr(order, "filled_at", None)
        if price is None or not isinstance(stamp, datetime) or stamp.tzinfo is None:
            continue
        candidates.append((stamp, price))
    return max(candidates, key=lambda item: item[0]) if candidates else None


def resolve_cycle_spend(available, configured):
    """ALL means nearly all verified spendable USD cash, not equity or margin.

    Reserve 1% for unknown fees, rounding and buying power fluctuations.
    """
    try:
        cash = Decimal(str(available))
        if not cash.is_finite() or cash < 0:
            return None
        if str(configured).strip().upper() == "ALL":
            amount = (cash * Decimal("0.99")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        else:
            amount = Decimal(str(configured)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        return amount if amount >= Decimal("1") and amount <= cash else None
    except Exception:
        return None


def xrp_cycle_preview(client, data_client, *, spend_usd=None,
                      pullback_pct="0.5", cooldown_minutes=30, now=None):
    base = {"readOnly": True, "canEnter": False, "action": "HOLD"}
    if spend_usd is None:
        return {**base, "reason": "per-cycle USD spending limit not configured"}
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.data.requests import CryptoLatestQuoteRequest
        positions = client.get_all_positions()
        open_orders = client.get_orders(filter=GetOrdersRequest(
            status=QueryOrderStatus.OPEN, limit=500))
        closed = client.get_orders(filter=GetOrdersRequest(
            status=QueryOrderStatus.CLOSED, limit=500))
        last = _filled_sell(closed)
        if last is None:
            return {**base, "reason": "no confirmed XRP sale found in broker order history"}
        account = client.get_account()
        quotes = data_client.get_crypto_latest_quote(
            CryptoLatestQuoteRequest(symbol_or_symbols="XRP/USD"))
        quote = quotes.get("XRP/USD") if isinstance(quotes, dict) else None
        if quote is None:
            return {**base, "reason": "Alpaca XRP/USD quote missing"}
        available = available_crypto_cash(account)
        actual_spend = resolve_cycle_spend(available, spend_usd)
        return assess_xrp_dip_entry(
            ask=getattr(quote, "ask_price", None),
            ask_at=getattr(quote, "timestamp", None),
            positions=[getattr(pos, "symbol", "") for pos in positions
                       if "crypto" in str(getattr(pos, "asset_class", "")).lower()],
            open_order_symbols=[getattr(order, "symbol", "") for order in open_orders],
            available_cash=available,
            spend_usd=actual_spend, last_sale_price=last[1],
            last_sale_at=last[0], last_sale_filled=True,
            pullback_pct=pullback_pct, cooldown_minutes=cooldown_minutes,
            now=now or datetime.now(timezone.utc),
        )
    except Exception as exc:
        return {**base, "reason": "broker verification unavailable: " + type(exc).__name__}
