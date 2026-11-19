from datetime import datetime, timedelta, timezone
from backend.tradebot_v2.engine import Position, OrderRecord, entry_gate, evaluate_pullback

NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)

def order(symbol, side, status, hours_ago=1):
    return OrderRecord(symbol, side, NOW - timedelta(hours=hours_ago), status)

def test_existing_holding_blocks():
    assert entry_gate("NVDA", [Position("NVDA", 1)], [], NOW).status == "RED"

def test_two_positions_block():
    assert entry_gate("AAPL", [Position("NVDA", 1), Position("MSFT", 1)], [], NOW).status == "RED"

def test_buy_today_blocks():
    assert entry_gate("AAPL", [], [order("AAPL", "buy", "filled")], NOW).status == "RED"

def test_pending_order_blocks():
    assert entry_gate("AAPL", [], [order("AAPL", "buy", "accepted")], NOW).status == "RED"

def test_sell_cooldown_blocks():
    assert entry_gate("AAPL", [], [order("AAPL", "sell", "filled")], NOW).status == "AMBER"

def test_missing_broker_state_blocks():
    assert entry_gate("AAPL", None, [], NOW).status == "RED"

def test_clean_entry_still_not_buy_authorization():
    assert entry_gate("AAPL", [], [], NOW).status == "AMBER"

def test_universe_restriction():
    assert entry_gate("TSLA", [], [], NOW).status == "RED"

def test_short_price_history_not_green():
    assert evaluate_pullback("AAPL", [100.0] * 10).status != "GREEN"
