"""Actual current-main market_sell_qty extracted via AST.

No import of the trading engine, no credentials, no market access, no live
broker. Verify alerts for accepted-but-untracked sell acknowledgements and
preserve existing successful submission behaviour.
"""
import ast
from pathlib import Path
from types import SimpleNamespace


SOURCE = Path(__file__).resolve().parents[1] / "backend/legacy/monolith.py"


def function_under_test(*, recorded):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    node = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "market_sell_qty"
    )
    code = compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec")
    class FakeClient:
        def submit_order(self, order):
            recorded["submissions"].append(order)
            return SimpleNamespace(id="alpaca-accepted-123", status="accepted", qty=4)
    ns = {
        "trading_client": FakeClient(),
        "MarketOrderRequest": lambda **kw: SimpleNamespace(**kw),
        "OrderSide": SimpleNamespace(SELL="sell"),
        "TimeInForce": SimpleNamespace(DAY="day", GTC="gtc"),
        "_manual_sell_is_crypto": lambda symbol: False,
        "floor_qty": lambda qty, decimals: round(qty, decimals),
        "register_pending_sell_order": lambda *args: recorded["persisted"],
        "add_alpaca_rejection_event": lambda *args: recorded["rejections"].append(args),
        "is_insufficient_qty_error": lambda err: False,
        "parse_available_qty": lambda err: 0,
        "today_str": lambda: "2026-11-11",
        "now_time": lambda: "15:00",
        "money_gbp": lambda usd: usd,
        "trade_events": recorded["events"],
        "lock_symbol_until_tomorrow": lambda symbol: recorded["locks"].append(symbol),
        "notify": lambda message: recorded["notifications"].append(message),
    }
    exec(code, ns)
    return ns["market_sell_qty"]


def state(persisted):
    return {"persisted": persisted, "submissions": [], "rejections": [],
            "events": [], "locks": [], "notifications": []}


def test_broker_ack_with_db_write_failure_raises_alert_but_never_retries():
    record = state(False)
    sell = function_under_test(recorded=record)
    sell("FMC", 4, entry=10, price=11, reason="AUTO SELL")
    assert len(record["submissions"]) == 1
    assert len(record["notifications"]) == 2
    assert "ACCOUNTING UNTRACKED" in record["notifications"][0]
    assert "do NOT retry automatically" in record["notifications"][0]
    assert record["events"][0]["accountingStatus"] == "PENDING_FILL_RECONCILIATION"
    assert record["locks"] == ["FMC"]


def test_successful_pending_registration_produces_no_failure_alert():
    record = state(True)
    sell = function_under_test(recorded=record)
    sell("FMC", 4, entry=10, price=11, reason="AUTO SELL")
    assert len(record["submissions"]) == 1
    assert len(record["notifications"]) == 1
    assert "SELL SUBMITTED" in record["notifications"][0]
    assert record["locks"] == ["FMC"]
