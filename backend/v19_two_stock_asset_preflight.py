"""Read-only Alpaca asset identity and notional eligibility validation.

Never submits an order or mutates account state.
"""
from typing import Any


def field(asset: Any, key: str):
    if isinstance(asset, dict):
        return asset.get(key, asset.get("class") if key == "asset_class" else None)
    return getattr(asset, key, None)


def enum_text(value):
    return str(getattr(value, "value", value) or "").strip().lower()


def check_asset(symbol: str, asset: Any) -> dict:
    symbol = str(symbol or "").strip().upper()
    name = str(field(asset, "name") or "")
    actual = str(field(asset, "symbol") or "").strip().upper()
    asset_class = enum_text(field(asset, "asset_class"))
    status = enum_text(field(asset, "status"))
    reasons = []
    if symbol not in {"TSLA", "SPCX"}:
        reasons.append("not_in_two_stock_watchlist")
    if actual != symbol:
        reasons.append("ticker_mismatch")
    if asset_class != "us_equity":
        reasons.append("not_us_equity")
    if status != "active":
        reasons.append("asset_inactive")
    if field(asset, "tradable") is not True:
        reasons.append("not_tradable")
    if field(asset, "fractionable") is not True:
        reasons.append("not_fractionable_for_notional_order")
    normalized_name = " ".join(name.lower().split())
    correct_company = (
        "tesla" in normalized_name if symbol == "TSLA"
        else "spacex" in normalized_name or "space exploration technologies" in normalized_name
        if symbol == "SPCX" else False
    )
    if not correct_company:
        reasons.append("issuer_identity_unverified")
    return {
        "symbol": symbol,
        "brokerSymbol": actual,
        "brokerName": name,
        "assetClass": asset_class,
        "status": status,
        "tradable": field(asset, "tradable") is True,
        "fractionable": field(asset, "fractionable") is True,
        "eligible": not reasons,
        "reasons": reasons,
    }


def check_from_broker(client: Any, symbol: str) -> dict:
    """Use existing Alpaca TradingClient for a read-only lookup."""
    try:
        return check_asset(symbol, client.get_asset(symbol))
    except Exception as exc:
        return {
            "symbol": str(symbol).upper(),
            "eligible": False,
            "reasons": ["broker_asset_lookup_failed"],
            "errorType": type(exc).__name__,
        }
