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

def test_rebuy_next_day_still_blocked_if_holding():
    assert entry_gate("AAPL", [Position("AAPL", 2)], [order("AAPL", "buy", "filled", 26)], NOW).status == "RED"

def test_recent_sell_blocks_even_after_new_day():
    assert entry_gate("AAPL", [], [order("AAPL", "sell", "filled", 13)], NOW).status == "AMBER"

def test_old_sale_does_not_authorize_buy():
    assert entry_gate("AAPL", [], [order("AAPL", "sell", "filled", 48)], NOW).status == "AMBER"

def test_signal_never_places_orders():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "backend" / "tradebot_v2"
    for file in root.glob("*.py"):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"submit_order", "cancel_order", "close_position", "close_all_positions"}

def test_two_pending_buys_reserve_both_slots():
    pending = [order("MSFT", "buy", "accepted"), order("NVDA", "buy", "new")]
    assert entry_gate("AAPL", [], pending, NOW).status == "RED"

def test_one_holding_and_one_pending_buy_reserve_slots():
    pending = [order("NVDA", "buy", "accepted")]
    assert entry_gate("AAPL", [Position("MSFT", 1)], pending, NOW).status == "RED"

def test_research_is_independent_of_broker_positions():
    prices = [100.0] * 10 + [102.0] * 10 + [104.0] * 9 + [102.0]
    research = evaluate_pullback("NVDA", prices)
    gate = entry_gate("NVDA", [Position("NVDA", 1)], [], NOW)
    assert gate.status == "RED"
    assert research.status in {"GREEN", "AMBER", "RED"}

def test_research_never_overrides_existing_position_guard():
    gate = entry_gate("MSFT", [Position("MSFT", 3)], [], NOW)
    assert gate.reason == "Already holding this stock"


def test_future_dated_order_fails_closed():
    future = OrderRecord("AAPL", "sell", NOW + timedelta(hours=2), "filled")
    gate = entry_gate("AAPL", [], [future], NOW)
    assert gate.status == "RED"
    assert "timestamp" in gate.reason.lower()


def test_non_finite_prices_cannot_produce_green_signal():
    for bad in (float("nan"), float("inf"), float("-inf")):
        assert evaluate_pullback("AAPL", [100.0] * 29 + [bad]).status != "GREEN"
