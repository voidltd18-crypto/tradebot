"""Stock-only capacity reporting and entry limit; no order submission."""
from decimal import Decimal


def stock_crypto_capacity(base_payload, trading_client, min_notional=1.0):
    payload = dict(base_payload)
    payload.update(enabled=True, effectiveMaxPositions=2, configuredMaxPositions=2,
                   hardSafetyCap=2, stockPositionLimit=2, cryptoPositionBucketLimit=0,
                   structuralAvailableSlots=0, affordableNewPositions=0, availableSlots=0)
    try:
        def number(value):
            result = Decimal(str(value))
            if not result.is_finite():
                raise ValueError('non-finite broker value')
            return result
        raw = trading_client.get_all_positions()
        if not isinstance(raw, list):
            raise ValueError('invalid positions')
        account = trading_client.get_account()
        cash = max(Decimal(0), min(number(account.cash), number(account.buying_power)))
        minimum = number(min_notional)
        if minimum <= 0:
            raise ValueError('invalid minimum')
        stocks, cryptos, seen = 0, 0, set()
        for position in raw:
            qty, value = number(position.qty), abs(number(position.market_value))
            symbol = str(position.symbol).upper()
            if not symbol or symbol in seen or qty < 0:
                raise ValueError('invalid or unsupported position')
            seen.add(symbol)
            if qty == 0 or value < Decimal('0.01'):
                continue
            asset = str(position.asset_class).lower()
            if 'crypto' in asset:
                cryptos += 1
            elif 'equity' in asset or 'stock' in asset:
                stocks += 1
            else:
                raise ValueError('unknown asset class')
        orders = trading_client.get('/orders', data={'status':'open','side':'buy','limit':1})
        if not isinstance(orders, list):
            raise ValueError('invalid orders')
        slots = max(0, 2-stocks)
        affordable = min(2, int(cash // minimum))
        payload.update(openPositions=stocks+cryptos, openStockPositions=stocks,
                       openCryptoPositions=cryptos, structuralAvailableSlots=slots,
                       affordableNewPositions=affordable, availableSlots=0 if orders else min(slots, affordable),
                       buyingPowerUsd=float(number(account.buying_power)),
                       reason='Pending buy blocks further entries' if orders else 'Two stock slots; existing risk and sizing gates still apply')
    except Exception:
        payload['reason'] = 'Broker positions, orders or funds unverified; new entries blocked'
    return payload


def install_stock_crypto_capacity(legacy):
    original = legacy.ai_position_capacity_payload
    def capacity():
        return stock_crypto_capacity(original(), legacy.trading_client,
                                     getattr(legacy, 'MIN_ORDER_NOTIONAL', 1.0))
    legacy.ai_position_capacity_payload = capacity
