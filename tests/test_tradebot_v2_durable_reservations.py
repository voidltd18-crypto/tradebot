import pytest
from backend.tradebot_v2.durable_reservations import reserve_offline


@pytest.mark.parametrize("symbol,side,quantity", [
    (None, "BUY", 1), ("TSLA", "BUY", 1), ("MSFT", "HOLD", 1),
    ("MSFT", "BUY", 0), ("MSFT", "BUY", -1),
    ("MSFT", "BUY", "NaN"), ("MSFT", "BUY", "Infinity"),
    ("MSFT", "BUY", "0.000000001"), ("MSFT", "BUY", "10000000000000000")
])
def test_invalid_request_fails_before_database(symbol, side, quantity):
    with pytest.raises(ValueError):
        reserve_offline("postgresql://unused", "req-1", symbol, side, quantity)


def test_missing_connection_or_request_id_fails_closed():
    with pytest.raises(ValueError):
        reserve_offline("", "req-1", "MSFT", "BUY", 1)
    with pytest.raises(ValueError):
        reserve_offline("postgresql://unused", "", "MSFT", "BUY", 1)
