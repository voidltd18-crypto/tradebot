from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
import sqlite3
from threading import Barrier
from types import SimpleNamespace

import pytest

from backend.stock_exit_reservation import emergency_latched, latch_emergency, recover_exits, reserve_exit
from backend.stock_ownership import init_stock_ownership, reserve_stock_purchase, verified_stock_quantity


@pytest.fixture
def portfolio(tmp_path):
    def connect():
        return sqlite3.connect(tmp_path / "ledger.sqlite")
    with connect() as conn:
        init_stock_ownership(conn)
        conn.execute("CREATE TABLE pending_sell_orders (alpaca_order_id TEXT PRIMARY KEY, accounting_status TEXT, accounted_qty TEXT)")
    account = SimpleNamespace(id="account", status="ACTIVE", trading_blocked=False, account_blocked=False,
                              trade_suspended_by_user=False, equity="100", cash="50", buying_power="50")
    orders, activities, positions, open_orders = {}, [], [], []
    broker = SimpleNamespace(
        get_account=lambda: account, get_all_positions=lambda: positions,
        get_order_by_client_id=lambda key: orders[key],
        get=lambda path, data: open_orders if path == "/orders" else
        [a for a in activities if a["transaction_time"] >= data["after"]],
    )
    return SimpleNamespace(**locals())


def filled_buy(p):
    client = reserve_stock_purchase(p.connect, p.broker, "AAPL", "50", "account")
    stamp = datetime.now(timezone.utc)
    p.orders[client] = SimpleNamespace(client_order_id=client, id="buy", created_at=stamp,
        status="filled", side="buy", symbol="AAPL", notional="50", filled_qty="1")
    p.activities.append(dict(id="fill1", symbol="AAPL", activity_type="FILL", side="buy",
                             qty="1", cum_qty="1", order_id="buy", transaction_time=stamp.isoformat()))
    p.positions.append(SimpleNamespace(symbol="AAPL", qty="1", qty_available="1", avg_entry_price="50"))
    return client


def register(*args):
    return True


def test_competing_workers_share_one_slot(portfolio):
    p = portfolio
    barrier = Barrier(2)
    def reserve(symbol):
        def capacity():
            barrier.wait(3)
            return True
        try:
            return reserve_stock_purchase(p.connect, p.broker, symbol, 40, "account", check_capacity=capacity)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(bool(result) for result in pool.map(reserve, ["AAPL", "MSFT"])) == 1


def test_concurrent_exit_and_lost_ack(portfolio):
    p = portfolio
    filled_buy(p)
    def reserve(_):
        try:
            return reserve_exit(p.connect, p.broker, "AAPL", ".5", "TRAIL")
        except (ValueError, sqlite3.IntegrityError):
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, range(2)))
    assert len([client for client in results if client]) == 1
    # Broker accepted but response and lookup are delayed.
    assert recover_exits(p.connect, p.broker, register) == {"checked": 1, "resolved": 0}
    assert reserve(0) is None


@pytest.mark.parametrize("status,filled", [("rejected", "0"), ("expired", "0"), ("canceled", ".2"), ("filled", ".5")])
def test_terminal_sell_needs_complete_evidence(portfolio, status, filled):
    p = portfolio
    filled_buy(p)
    client = reserve_exit(p.connect, p.broker, "AAPL", ".5", "PARTIAL PROFIT TAKE")
    stamp = datetime.now(timezone.utc)
    order = SimpleNamespace(client_order_id=client, symbol="AAPL", side="sell", id="sell", qty=".5",
                            status="partially_filled", filled_qty=filled, created_at=stamp)
    p.orders[client] = order
    assert recover_exits(p.connect, p.broker, register)["resolved"] == 0
    order.status = status
    p.open_orders.append({"id": "open", "symbol": "AAPL"})
    assert recover_exits(p.connect, p.broker, register)["resolved"] == 0
    p.open_orders.clear()
    remaining = Decimal(1) - Decimal(filled)
    if Decimal(filled):
        assert recover_exits(p.connect, p.broker, register)["resolved"] == 0
        event = dict(id="sellfill", symbol="AAPL", side="sell", order_id="sell", qty=filled,
                     cum_qty=filled, transaction_time=stamp.isoformat(), activity_type="FILL")
        p.activities.extend([event, event.copy()])
        p.positions[0].qty = p.positions[0].qty_available = str(remaining)
        assert recover_exits(p.connect, p.broker, register)["resolved"] == 0
        with p.connect() as conn:
            conn.execute("INSERT INTO pending_sell_orders VALUES ('sell','PROCESSED',?)", (filled,))
    assert recover_exits(p.connect, p.broker, register)["resolved"] == 1
    assert recover_exits(p.connect, p.broker, register)["checked"] == 0
    assert verified_stock_quantity(p.connect, p.broker, "AAPL") == remaining
    p.activities.append(dict(p.activities[0], id="manual", order_id="external"))
    assert verified_stock_quantity(p.connect, p.broker, "AAPL") is None


def test_latch_survives_reconnect_and_never_sends_an_order(portfolio):
    p = portfolio
    filled_buy(p)
    assert not emergency_latched(p.connect)
    latch_emergency(p.connect)
    latch_emergency(p.connect)
    assert emergency_latched(p.connect)
    with pytest.raises(ValueError, match="emergency stop"):
        reserve_exit(p.connect, p.broker, "AAPL", ".5", "STOP")


def test_scan_failure_preserves_later_decisions_and_quote_times():
    import ast
    from pathlib import Path
    from backend.stock_broker_state import BrokerStateUnverified

    def evaluate(scans, scan_decisions, **unused):
        row, = scans
        symbol = row["symbol"]
        if symbol == "AMD":
            raise BrokerStateUnverified("Broker state unverified: positions (timeout)")
        scan_decisions[symbol] = dict(symbol=symbol, stage="final_gate", decision="APPROVED", reason="passed")
        return scans

    source = Path(__file__).resolve().parents[1] / "backend/legacy/monolith.py"
    fn = next(node for node in ast.parse(source.read_text()).body
              if isinstance(node, ast.FunctionDef) and node.name == "evaluate_stock_scan")
    scope = dict(v17_live_entry_gate_pipeline=evaluate, BrokerStateUnverified=BrokerStateUnverified,
                 datetime=datetime, UTC=timezone.utc)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), "exec"), scope)
    stamp = datetime.now(timezone.utc)
    scans = [dict(symbol=s, confidence=.9, quality_score=1, spread=.01, quoteTimestamp=stamp.isoformat())
             for s in ("AMD", "AAPL")]
    errors = {"ORCL": dict(symbol="ORCL", decision="REJECTED", stage="scan", reason="stale quote")}
    survivors, snapshot = scope[fn.name](scans, ["ORCL", "AMD", "AAPL"], errors, stamp)
    assert [row["symbol"] for row in survivors] == ["AAPL"]
    assert not snapshot["evaluationComplete"]
    assert len(snapshot["rows"]) == snapshot["attemptedCount"] == 3
    assert errors["AMD"]["reason"].endswith("(timeout)")
    assert errors["AAPL"]["quoteTimestamp"] == stamp.isoformat()
