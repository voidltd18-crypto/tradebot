"""Manual Sell All must use broker-native 100% crypto liquidation (no quantity truncation)."""
import ast
from pathlib import Path
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"


def load(name, ns):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(SOURCE), "exec"), ns)
    return ns[name]


def make_harness(*, crypto=True, fail=False):
    calls = []
    class Broker:
        def close_position(self, symbol):
            calls.append(("close_all", symbol))
            if fail:
                raise RuntimeError("broker rejected close")
            return SimpleNamespace(id="order-crypto", status="accepted", qty="0.00003041")
        def submit_order(self, order):
            calls.append(("submit_qty", order.qty))
            return SimpleNamespace(id="order-stock", status="accepted")
    ns = {
        "trading_client": Broker(),
        "_manual_sell_is_crypto": lambda sym: crypto,
        "floor_qty": lambda qty, decimals=6: int(qty * (10**decimals)) / (10**decimals),
        "MarketOrderRequest": lambda **kwargs: SimpleNamespace(**kwargs),
        "OrderSide": SimpleNamespace(SELL="sell"),
        "TimeInForce": SimpleNamespace(GTC="gtc", DAY="day"),
        "is_insufficient_qty_error": lambda text: False,
        "parse_available_qty": lambda text: None,
        "add_alpaca_rejection_event": lambda *args: calls.append(("rejected", args)),
        "register_pending_sell_order": lambda *args: calls.append(("pending", args)) or True,
        "money_gbp": lambda v: v * 0.75,
        "today_str": lambda: "2026-11-09",
        "now_time": lambda: "16:30:00",
        "trade_events": [],
        "lock_symbol_until_tomorrow": lambda s: None,
        "notify": lambda s: None,
    }
    return load("market_sell_qty", ns), calls, ns


def test_manual_crypto_sell_closes_entire_broker_position_without_sizing_qty():
    sell, calls, ns = make_harness()
    sell("BTCUSD", 0.00003041, reason="MANUAL SYMBOL SELL")
    assert ("close_all", "BTCUSD") in calls
    assert not any(k == "submit_qty" for k, _ in calls)
    pending = next(v for k, v in calls if k == "pending")
    assert pending[2] == 0.00003041
    assert ns["trade_events"][0]["accountingStatus"] == "PENDING_FILL_RECONCILIATION"


def test_manual_crypto_close_rejection_not_retried_as_smaller_order():
    sell, calls, _ = make_harness(fail=True)
    try:
        sell("BTCUSD", 0.00003041, reason="MANUAL SYMBOL SELL")
    except RuntimeError:
        pass
    else:
        raise AssertionError("A rejected Sell All must fail, not pretend success")
    assert any(k == "rejected" for k, _ in calls)
    assert not any(k == "submit_qty" for k, _ in calls)


def test_stock_manual_sell_retains_existing_quantity_order_path():
    sell, calls, _ = make_harness(crypto=False)
    sell("TSLA", 1.2345679, reason="MANUAL SYMBOL SELL")
    qty = next(v for k, v in calls if k == "submit_qty")
    assert qty == 1.234567


def test_auto_crypto_sell_still_uses_prior_quantity_path():
    sell, calls, _ = make_harness()
    sell("BTCUSD", 0.0116709, reason="AUTO SELL")
    qty = next(v for k, v in calls if k == "submit_qty")
    assert qty == 0.01167


def test_small_crypto_residual_may_pass_manual_close_gate():
    src = SOURCE.read_text(encoding="utf-8")
    assert "manual_crypto_close = str(reason).upper().startswith" in src
    assert "qty <= DUST_THRESHOLD and not manual_crypto_close" in src
    assert "if has_open_order(symbol):" in src
