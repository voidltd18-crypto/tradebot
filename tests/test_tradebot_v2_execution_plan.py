from datetime import datetime, timezone
from decimal import Decimal

from backend.tradebot_v2.engine import Position
from backend.tradebot_v2.execution_plan import plan_buy, plan_sell


NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)


def test_buy_remains_disabled_even_with_verified_inputs():
    p = plan_buy("AAPL", "1", [], [], NOW, market_data_verified=True,
                 durable_reservation_verified=True)
    assert not p.permitted and p.side == "BUY"


def test_buy_missing_inputs_fail_closed():
    assert not plan_buy("AAPL", 1, None, None, NOW).permitted
    assert not plan_buy("TSLA", 1, [], [], NOW).permitted
    assert not plan_buy("AAPL", float("nan"), [], [], NOW).permitted
    assert not plan_buy("AAPL", -1, [], [], NOW).permitted


def test_two_positions_block_buy():
    p = plan_buy("AAPL", 1, [Position("MSFT", 1), Position("NVDA", 1)], [], NOW,
                 market_data_verified=True, durable_reservation_verified=True)
    assert not p.permitted and "Maximum two" in p.reason


def test_manual_shares_cannot_be_sold():
    p = plan_sell("MSFT", "1", "1", "3", verified_bot_origin=False,
                  ledger_reconciled=True, market_data_verified=True)
    assert not p.permitted and "ownership" in p.reason.lower()


def test_sell_exceeding_bot_inventory_blocked():
    p = plan_sell("MSFT", "2", "1", "3", verified_bot_origin=True,
                  ledger_reconciled=True, market_data_verified=True)
    assert not p.permitted and "exceeds" in p.reason


def test_verified_sell_still_not_executable():
    p = plan_sell("MSFT", Decimal("0.5"), "1", "3", verified_bot_origin=True,
                  ledger_reconciled=True, market_data_verified=True)
    assert not p.permitted and "disabled" in p.reason


def test_no_broker_order_methods_in_execution_planner():
    import ast
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "backend/tradebot_v2/execution_plan.py"
    tree = ast.parse(path.read_text())
    forbidden = {"submit_order", "cancel_order", "close_position", "close_all_positions"}
    assert not any(isinstance(n, ast.Attribute) and n.attr in forbidden for n in ast.walk(tree))
