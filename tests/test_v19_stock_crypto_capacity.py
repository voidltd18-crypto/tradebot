from types import SimpleNamespace
from backend.v19_stock_crypto_capacity import stock_crypto_capacity


def pos(symbol, asset_class, value=5):
    return SimpleNamespace(symbol=symbol, asset_class=asset_class, qty="1", market_value=str(value))


class Broker:
    def __init__(self, positions, cash=50):
        self.positions = positions
        self.cash = cash

    def get_all_positions(self):
        return self.positions

    def get_account(self):
        return SimpleNamespace(buying_power=str(self.cash))


def test_crypto_does_not_block_one_stock_slot():
    result = stock_crypto_capacity({}, Broker([pos("XRPUSD", "crypto")]))
    assert result["effectiveMaxPositions"] == 2
    assert result["openCryptoPositions"] == 1
    assert result["availableSlots"] == 1


def test_existing_stock_blocks_another_stock():
    result = stock_crypto_capacity({}, Broker([pos("MSFT", "us_equity"), pos("XRPUSD", "crypto")]))
    assert result["openStockPositions"] == 1
    assert result["availableSlots"] == 0


def test_multiple_manual_crypto_positions_still_do_not_consume_stock_slot():
    result = stock_crypto_capacity({}, Broker([pos("XRPUSD", "crypto"), pos("SOLUSD", "crypto")]))
    assert result["availableSlots"] == 1


def test_insufficient_cash_blocks_entry():
    result = stock_crypto_capacity({}, Broker([pos("XRPUSD", "crypto")], cash=0))
    assert result["availableSlots"] == 0


def test_unknown_asset_class_fails_closed():
    result = stock_crypto_capacity({}, Broker([pos("OTHER", "unknown")]))
    assert result["availableSlots"] == 0


def test_broker_failure_fails_closed():
    class Failing:
        def get_all_positions(self):
            raise RuntimeError("broker offline")
    assert stock_crypto_capacity({}, Failing())["availableSlots"] == 0
