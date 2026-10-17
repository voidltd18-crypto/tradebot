"""Exercise the production Alpaca reconciliation loop with fake broker orders and SQLite.

No network, broker credentials, live trading, or Render services required.
"""
import ast
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

SOURCE = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"


def extract(name, ns):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(SOURCE), "exec"), ns)
    return ns[name]


def make_order(order_id, status, qty, price=12.0):
    return SimpleNamespace(
        id=order_id, symbol="MARA", side="sell", status=status,
        filled_qty=str(qty), filled_avg_price=str(price),
        submitted_at=datetime(2026, 10, 17, tzinfo=timezone.utc),
    )


def harness(tmp_path):
    path = tmp_path / "trades.sqlite3"
    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    conn = connect()
    conn.executescript("""
        CREATE TABLE trades (
            alpaca_order_id TEXT PRIMARY KEY, symbol TEXT, side TEXT,
            qty REAL, price REAL
        );
        CREATE TABLE closed_trades (
            source_sell_order_id TEXT, qty REAL, pnl REAL, pnl_pct REAL
        );
        CREATE TABLE pending_sell_orders (
            alpaca_order_id TEXT PRIMARY KEY, accounting_status TEXT,
            accounted_qty REAL, accounted_pnl REAL, updated_at TEXT
        );
    """)
    conn.commit()
    conn.close()
    orders = []
    memory = []
    vault = []

    def save(event, source=""):
        conn = connect()
        conn.execute(
            "INSERT OR REPLACE INTO trades VALUES (?, ?, ?, ?, ?)",
            (event["alpacaOrderId"], event["symbol"], event["side"],
             event["qty"], event["price"]),
        )
        conn.commit()
        conn.close()

    def rebuild():
        # Simulate the FIFO matcher: one filled sell matched to an existing
        # purchase at $10/share. The production loop's decision logic is real.
        conn = connect()
        conn.execute("DELETE FROM closed_trades")
        for row in conn.execute("SELECT * FROM trades WHERE side='SELL'").fetchall():
            qty = float(row["qty"])
            price = float(row["price"])
            conn.execute(
                "INSERT INTO closed_trades VALUES (?, ?, ?, ?)",
                (row["alpaca_order_id"], qty, (price - 10) * qty,
                 (price / 10 - 1) * 100),
            )
        conn.commit()
        conn.close()
        return {"matchedClosedTrades": 1}

    ns = {
        "Dict": Dict, "Any": Any, "time": time, "datetime": datetime,
        "UTC": timezone.utc, "SQLITE_ENABLED": True,
        "AUTO_REPORT_SYNC_ENABLED": True, "AUTO_REPORT_SYNC_INTERVAL_SECONDS": 0,
        "AUTO_REPORT_SYNC_ORDER_LIMIT": 500, "auto_report_last_sync_ts": 0,
        "auto_report_last_result": {},
        "init_db": lambda: None, "db_connect": connect,
        "restore_today_sell_locks_from_db": lambda: [],
        "GetOrdersRequest": lambda **kw: kw, "get_query_order_status_all": lambda: "all",
        "trading_client": SimpleNamespace(get_orders=lambda filter: list(orders)),
        "get_usd_to_gbp_rate": lambda: 0.75,
        "money_gbp": lambda x: x * 0.75,
        "today_str": lambda: "2026-10-17", "now_time": lambda: "12:00:00",
        "parse_order_timestamp": lambda order: order.submitted_at,
        "get_order_id": lambda order: order.id,
        "get_order_symbol": lambda order: order.symbol,
        "get_order_side": lambda order: order.side.upper(),
        "get_order_qty": lambda order: float(order.filled_qty),
        "get_order_price": lambda order: float(order.filled_avg_price),
        "_trade_order_exists": lambda oid: _exists(connect, oid),
        "save_trade_to_db": save, "rebuild_closed_trades_from_orders": rebuild,
        "update_stock_memory_from_sell": lambda symbol, pnl, pct, order_id: memory.append((order_id, pnl)),
        "profit_vault_bank_realised_profit": lambda pnl, symbol, reason, order_id: vault.append((order_id, pnl)),
    }
    extract("order_is_filled", ns)
    extract("order_execution_is_final", ns)
    sync = extract("sync_recent_filled_orders_to_reports", ns)
    return connect, orders, memory, vault, sync


def _exists(connect, oid):
    conn = connect()
    found = conn.execute("SELECT 1 FROM trades WHERE alpaca_order_id=?", (oid,)).fetchone()
    conn.close()
    return bool(found)


def register(connect, oid):
    conn = connect()
    conn.execute(
        "INSERT INTO pending_sell_orders VALUES (?, 'PENDING', 0, 0, '')",
        (oid,),
    )
    conn.commit()
    conn.close()


def test_partial_fill_then_final_and_restart(tmp_path):
    connect, orders, memory, vault, sync = harness(tmp_path)
    register(connect, "order-1")
    orders.append(make_order("order-1", "partially_filled", 0.5))
    assert sync(force=True)["ok"]
    assert not memory and not vault
    conn = connect()
    assert conn.execute("SELECT qty FROM trades WHERE alpaca_order_id='order-1'").fetchone()[0] == 0.5
    conn.close()

    orders[0] = make_order("order-1", "filled", 1.0)
    assert sync(force=True)["ok"]
    assert memory == [("order-1", 2.0)]
    assert vault == [("order-1", 2.0)]
    conn = connect()
    row = conn.execute("SELECT accounting_status, accounted_qty FROM pending_sell_orders").fetchone()
    assert tuple(row) == ("PROCESSED", 1.0)
    conn.close()

    # A new process would re-read the persisted PROCESSED state.
    assert sync(force=True)["ok"]
    assert len(memory) == len(vault) == 1


def test_old_historical_fill_never_recredits_vault(tmp_path):
    connect, orders, memory, vault, sync = harness(tmp_path)
    orders.append(make_order("legacy-sell", "filled", 1.0))
    assert sync(force=True)["ok"]
    assert not memory and not vault


def test_partially_filled_cancelled_order_accounts_once(tmp_path):
    connect, orders, memory, vault, sync = harness(tmp_path)
    register(connect, "order-2")
    orders.append(make_order("order-2", "canceled", 0.25))
    assert sync(force=True)["ok"]
    assert memory == [("order-2", 0.5)]
    assert vault == [("order-2", 0.5)]
    assert sync(force=True)["ok"]
    assert len(memory) == len(vault) == 1


def test_actual_fifo_matcher_uses_confirmed_prices(tmp_path):
    from typing import List
    db_path = tmp_path / "fifo.sqlite3"
    def connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    conn = connect()
    conn.executescript("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, alpaca_order_id TEXT,
            timestamp TEXT, day TEXT, time TEXT, symbol TEXT, side TEXT,
            qty REAL, price REAL, amount REAL
        );
        CREATE TABLE closed_trades (
            source_sell_order_id TEXT, source_buy_order_id TEXT, symbol TEXT,
            qty REAL, entry_price REAL, exit_price REAL, pnl REAL, pnl_pct REAL
        );
        INSERT INTO trades (alpaca_order_id, timestamp, day, time, symbol, side, qty, price)
        VALUES ('buy-1','2026-10-17T10:00:00+00:00','2026-10-17','10:00:00','MARA','BUY',2,10);
        INSERT INTO trades (alpaca_order_id, timestamp, day, time, symbol, side, qty, price)
        VALUES ('sell-1','2026-10-17T11:00:00+00:00','2026-10-17','11:00:00','MARA','SELL',1,12);
    """)
    conn.commit()
    conn.close()
    def save_closed(trade):
        conn = connect()
        conn.execute(
            "INSERT INTO closed_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (trade["sourceSellOrderId"], trade["sourceBuyOrderId"],
             trade["symbol"], trade["qty"], trade["entryPrice"],
             trade["exitPrice"], trade["pnl"], trade["pnlPct"]),
        )
        conn.commit()
        conn.close()
    def clear():
        conn = connect()
        conn.execute("DELETE FROM closed_trades")
        conn.commit()
        conn.close()
    ns = {
        "SQLITE_ENABLED": True, "init_db": lambda: None,
        "db_connect": connect, "clear_closed_trades": clear,
        "get_usd_to_gbp_rate": lambda: 0.75,
        "save_closed_trade_to_db": save_closed,
        "Dict": Dict, "List": List, "Any": Any,
    }
    rebuild = extract("rebuild_closed_trades_from_orders", ns)
    result = rebuild()
    assert result["matchedClosedTrades"] == 1
    conn = connect()
    row = conn.execute("SELECT qty, entry_price, exit_price, pnl FROM closed_trades").fetchone()
    assert tuple(row) == (1.0, 10.0, 12.0, 2.0)
    conn.close()
