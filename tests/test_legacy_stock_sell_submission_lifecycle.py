"""Actual legacy SELL submission regression with mock Alpaca transport.

Extracts one function AST only; does not import/run live monolith.
Investigates accepted/rejected broker acknowledgement and persistence
failure (known source risk). Never sends a real order.
"""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"


class FakeBroker:
    def __init__(self, *, status="accepted", error=None):
        self.status = status
        self.error = error
        self.orders = []

    def submit_order(self, order):
        self.orders.append(order)
        if self.error:
            raise RuntimeError(self.error)
        return SimpleNamespace(id="mock-order-001", status=self.status, qty=order.qty)


def make_market_sell(*, registration_ok=True, status="accepted", broker_error=None):
    root = ast.parse(SRC.read_text(encoding="utf-8"))
    node = next(n for n in root.body if isinstance(n, ast.FunctionDef) and n.name == "market_sell_qty")
    broker = FakeBroker(status=status, error=broker_error)
    events, pending, locks, rejections, notifications = [], [], [], [], []
    ctx = {
        "_manual_sell_is_crypto": lambda symbol: False,
        "floor_qty": lambda qty, decimals: round(qty, decimals),
        "MarketOrderRequest": lambda **kw: SimpleNamespace(**kw),
        "OrderSide": SimpleNamespace(SELL="sell"),
        "TimeInForce": SimpleNamespace(DAY="day", GTC="gtc"),
        "trading_client": broker,
        "add_alpaca_rejection_event": lambda *args: rejections.append(args),
        "is_insufficient_qty_error": lambda err: False,
        "parse_available_qty": lambda err: None,
        "register_pending_sell_order": lambda *args: (pending.append(args) or registration_ok),
        "today_str": lambda: "2026-11-10",
        "now_time": lambda: "13:00",
        "money_gbp": lambda value: value * 0.8,
        "trade_events": events,
        "lock_symbol_until_tomorrow": lambda symbol: locks.append(symbol),
        "notify": lambda value: notifications.append(value),
    }
    mod = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(mod, str(SRC), "exec"), ctx)
    return ctx["market_sell_qty"], broker, events, pending, locks, rejections


def test_accepted_order_is_not_recorded_as_realized_fill():
    submit, broker, events, pending, locks, rejected = make_market_sell()
    submit("FMC", 10, entry=5.48, price=5.65, reason="MONEY MODE TRAILING PROFIT")
    assert len(broker.orders) == 1
    assert len(pending) == 1
    assert events[0]["accountingStatus"] == "PENDING_FILL_RECONCILIATION"
    assert events[0]["estimatedPnl"] > 0
    assert "pnl" not in events[0]
    assert locks == ["FMC"]
    assert not rejected


def test_rejected_broker_order_does_not_mark_sell_or_lock():
    submit, broker, events, pending, locks, rejected = make_market_sell(
        broker_error="mock order rejected"
    )
    with pytest.raises(RuntimeError, match="mock order rejected"):
        submit("FMC", 10, entry=5.48, price=5.65)
    assert len(broker.orders) == 1
    assert not pending and not events and not locks
    assert len(rejected) == 1


def test_pending_record_failure_is_currently_nonfatal_risk():
    # Characterization test: this is NOT an endorsement of current behavior.
    # A broker-accepted sell continues even if the app fails to persist the
    # pending order ID. Fix requires coordinated production order reconciliation.
    submit, broker, events, pending, locks, rejected = make_market_sell(
        registration_ok=False
    )
    submit("FMC", 10, entry=5.48, price=5.65)
    assert len(broker.orders) == 1
    assert len(pending) == 1
    assert events[0]["accountingStatus"] == "PENDING_FILL_RECONCILIATION"
    assert locks == ["FMC"]
    assert not rejected


def test_zero_quantity_does_not_submit_anything():
    submit, broker, events, pending, locks, rejected = make_market_sell()
    assert submit("FMC", 0) is None
    assert not broker.orders and not events and not locks
