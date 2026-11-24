import ast
from pathlib import Path

import pytest

from backend.stock_buy_risk import cap_stock_buy_notional


def cap(**overrides):
    args = dict(requested=1000, equity=1000, cash=1000, buying_power=2000,
                stop_distance_pct=10, minimum_order=1)
    return cap_stock_buy_notional(**(args | overrides))


def test_full_buy_is_capped_and_wider_stop_reduces_size():
    assert cap() == 48.54
    assert cap(stop_distance_pct=15) == 32.67
    assert cap(requested=20) == 20


def test_cash_and_buying_power_limit_position_without_borrowing():
    assert cap(cash=12) == 11.96
    assert cap(buying_power=12) == 11.96


@pytest.mark.parametrize("overrides", [
    {"cash": 0}, {"equity": "NaN"}, {"buying_power": None},
    {"stop_distance_pct": 0}, {"stop_distance_pct": 100}, {"minimum_order": 50},
])
def test_invalid_inputs_and_subminimum_orders_block(overrides):
    with pytest.raises(ValueError, match="BUY BLOCKED"):
        cap(**overrides)


def test_original_stock_order_boundary_applies_cap_before_submission():
    path = Path(__file__).resolve().parents[1] / "backend/legacy/monolith.py"
    module = ast.parse(path.read_text(encoding="utf-8"))
    entry = next(node for node in module.body
                 if isinstance(node, ast.FunctionDef) and node.name == "market_buy_notional")
    calls = [node for node in ast.walk(entry) if isinstance(node, ast.Call)]
    cap_line = next(node.lineno for node in calls
                    if isinstance(node.func, ast.Name) and node.func.id == "cap_stock_buy_notional")
    submit_line = next(node.lineno for node in calls
                       if isinstance(node.func, ast.Attribute) and node.func.attr == "submit_order")
    assert cap_line < submit_line
