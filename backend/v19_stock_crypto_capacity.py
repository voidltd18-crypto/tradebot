"""Stock-only autonomous entry capacity; manual crypto holdings occupy a separate bucket.

No order execution, exit management, or broker balance checks are changed.
"""
from __future__ import annotations


def stock_crypto_capacity(base_payload, trading_client, min_notional=1.0):
    """Fail closed when Alpaca positions or cash cannot be verified."""
    payload = dict(base_payload)
    payload.update({
        "effectiveMaxPositions": 2,
        "configuredMaxPositions": 2,
        "hardSafetyCap": 2,
        "stockPositionLimit": 1,
        "cryptoPositionBucketLimit": 1,
        "structuralAvailableSlots": 0,
        "affordableNewPositions": 0,
        "availableSlots": 0,
    })
    try:
        raw = trading_client.get_all_positions()
        account = trading_client.get_account()
        cash = max(0.0, float(account.buying_power))
        stocks = 0
        cryptos = 0
        for position in raw:
            qty = float(position.qty)
            value = abs(float(position.market_value))
            if qty <= 0 or value < 0.01:
                continue
            asset_class = str(getattr(position, "asset_class", "")).lower()
            symbol = str(getattr(position, "symbol", "")).upper()
            if "crypto" in asset_class or "/" in symbol or symbol.endswith("USD") and "equity" not in asset_class and "us_equity" not in asset_class:
                cryptos += 1
            elif "equity" in asset_class or "stock" in asset_class:
                stocks += 1
            else:
                payload["reason"] = "Unknown broker asset class: stock entry capacity unverified"
                return payload
        stock_slot = int(stocks == 0)
        affordable = int(cash > max(0.0, float(min_notional)))
        payload.update({
            "openPositions": stocks + cryptos,
            "openStockPositions": stocks,
            "openCryptoPositions": cryptos,
            "structuralAvailableSlots": stock_slot,
            "affordableNewPositions": affordable,
            "availableSlots": min(stock_slot, affordable),
            "buyingPowerUsd": round(cash, 2),
            "reason": "One autonomous stock slot independent of manually held crypto; broker buying-power and order risk gates still apply.",
        })
    except Exception:
        payload["reason"] = "Broker positions or buying power unverified; new stock entries blocked"
    return payload


def install_stock_crypto_capacity(legacy):
    original = legacy.ai_position_capacity_payload

    def capacity():
        return stock_crypto_capacity(
            original(),
            legacy.trading_client,
            min_notional=getattr(legacy, "MIN_ORDER_NOTIONAL", 1.0),
        )

    legacy.ai_position_capacity_payload = capacity
