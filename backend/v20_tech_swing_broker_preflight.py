"""Fail-closed, read-only preflight for a future tech swing stock order.

No Alpaca SDK imports, no broker mutation, and no live order authorization.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

TECH = frozenset({"AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA"})


def _decimal(value):
    try:
        result = Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        raise ValueError("invalid monetary amount")
    if not result.is_finite():
        raise ValueError("nonfinite monetary amount")
    return result


def _field(obj, key):
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def inspect_candidate(*, symbol, account, asset, clock, positions, open_orders,
                      notional, signal_at, now=None, buys_paused=True,
                      explicit_review=False):
    """Report every known blocker. Always deny execution, even if preflight passes."""
    reasons = []
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    symbol = str(symbol or "").upper()
    if symbol not in TECH:
        reasons.append("symbol_not_in_tech_universe")
    if buys_paused:
        reasons.append("stock_buys_paused")
    if not explicit_review:
        reasons.append("human_review_missing")
    if _field(account, "trading_blocked") is not False or _field(account, "account_blocked") is not False:
        reasons.append("account_status_unverified")
    if str(_field(account, "status") or "").upper() != "ACTIVE":
        reasons.append("account_not_active")
    if _field(asset, "symbol") != symbol or str(_field(asset, "asset_class") or "").lower() not in {"us_equity", "assetclass.us_equity"}:
        reasons.append("asset_identity_unverified")
    if _field(asset, "tradable") is not True or _field(asset, "fractionable") is not True:
        reasons.append("asset_not_tradable_fractional")
    if _field(clock, "is_open") is not True:
        reasons.append("market_not_open")
    if not isinstance(signal_at, datetime) or signal_at.tzinfo is None or signal_at.utcoffset() is None or signal_at > now or (now - signal_at).total_seconds() > 86400:
        reasons.append("stale_or_invalid_signal")
    try:
        equity = _decimal(_field(account, "equity"))
        power = _decimal(_field(account, "buying_power"))
        amount = _decimal(notional)
        if equity <= 0 or amount <= 0 or amount > equity * Decimal("0.25") or amount > power:
            reasons.append("allocation_or_buying_power_limit")
    except ValueError:
        reasons.append("financial_values_unverified")
    if not isinstance(positions, list) or not isinstance(open_orders, list):
        reasons.append("broker_inventory_unverified")
    else:
        if positions:
            reasons.append("existing_position_blocks_new_tech_entry")
        if open_orders:
            reasons.append("open_order_blocks_new_entry")
    return {"symbol": symbol, "readOnly": True, "ordersSubmitted": 0,
            "preflightChecksPassed": not reasons,
            "liveOrdersAuthorized": False, "reasons": reasons,
            "note": "Read-only checks are not a permission to trade; separate reviewed order path required."}
