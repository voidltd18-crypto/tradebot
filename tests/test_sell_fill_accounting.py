"""Regression tests for confirmed-fill accounting, without starting TradeBot.

Run from the repository root: python -m pytest tests/test_sell_fill_accounting.py -q
"""
import ast
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "backend" / "legacy" / "monolith.py"


def load_function(name, namespace):
    source = ast.parse(SOURCE.read_text(encoding="utf-8"))
    matches = [n for n in source.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    assert len(matches) == 1, f"Expected exactly one function: {name}"
    module = ast.Module(body=matches, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), namespace)
    return namespace[name]


def order(status, qty=1, price=12):
    return SimpleNamespace(status=status, filled_qty=qty, filled_avg_price=price)


def test_sell_submission_does_not_record_realised_profit():
    source = ast.parse(SOURCE.read_text(encoding="utf-8"))
    sell = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == "market_sell_qty")
    called = set()
    for n in ast.walk(sell):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            called.add(n.func.id)
    assert "add_trade_history_event" not in called
    assert "update_stock_memory_from_sell" not in called
    assert "profit_vault_bank_realised_profit" not in called
    assert "register_pending_sell_order" in called


def test_terminal_fills_and_partial_fills():
    ns = {}
    load_function("order_is_filled", ns)
    is_final = load_function("order_execution_is_final", ns)
    assert is_final(order("filled"))
    assert is_final(order("OrderStatus.FILLED"))
    assert not is_final(order("partially_filled", 0.5))
    assert is_final(order("canceled", 0.5))
    assert not is_final(order("canceled", 0))
    assert not is_final(order("accepted", 0))


def test_stock_memory_order_id_is_idempotent_after_restart():
    saved = {}
    ns = {
        "STOCK_MEMORY_ENABLED": True,
        "MEMORY_MIN_TRADES_FOR_TRUST": 2,
        "MEMORY_GOOD_WINRATE": 0.6,
        "MEMORY_BAD_WINRATE": 0.4,
        "stock_memory": saved,
        "save_stock_memory": lambda: None,
        "refresh_blacklist_from_memory": lambda symbol: None,
    }
    load_function("get_memory", ns)
    update = load_function("update_stock_memory_from_sell", ns)
    update("MARA", 4, 2, order_id="alpaca-1")
    update("MARA", 4, 2, order_id="alpaca-1")
    assert saved["MARA"]["trades"] == 1
    assert saved["MARA"]["totalPnl"] == 4
    # Simulated restart: retain persisted symbol memory but reload function.
    update = load_function("update_stock_memory_from_sell", ns)
    update("MARA", 4, 2, order_id="alpaca-1")
    assert saved["MARA"]["trades"] == 1
    update("MARA", -1, -0.5, order_id="alpaca-2")
    assert saved["MARA"]["trades"] == 2
    assert saved["MARA"]["totalPnl"] == 3


def test_pending_sell_registration_is_restart_safe(tmp_path):
    import sqlite3
    from datetime import datetime, timezone
    db_path = tmp_path / "orders.sqlite3"
    def connect():
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS pending_sell_orders ("
            "alpaca_order_id TEXT PRIMARY KEY, symbol TEXT, requested_qty REAL, reason TEXT,"
            "submitted_at TEXT, initial_status TEXT, accounting_status TEXT,"
            "accounted_qty REAL, accounted_pnl REAL, updated_at TEXT)"
        )
        return conn
    ns = {
        "SQLITE_ENABLED": True,
        "init_db": lambda: None,
        "db_connect": connect,
        "datetime": datetime,
        "UTC": timezone.utc,
    }
    register = load_function("register_pending_sell_order", ns)
    assert register("sell-1", "GOOG", 1, "TRAIL", "accepted")
    assert register("sell-1", "GOOG", 1, "TRAIL", "accepted")
    conn = connect()
    assert conn.execute("SELECT COUNT(*) FROM pending_sell_orders").fetchone()[0] == 1
    conn.close()


def test_reconciliation_requires_terminal_order_and_fifo_match():
    source = ast.parse(SOURCE.read_text(encoding="utf-8"))
    sync = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == "sync_recent_filled_orders_to_reports")
    text = ast.get_source_segment(SOURCE.read_text(encoding="utf-8"), sync)
    assert "order_execution_is_final(order)" in text
    assert "pending_sell_orders" in text
    assert "abs(matched_qty - filled_qty) > tolerance" in text
    assert "accounting_status='PROCESSED'" in text
    assert "actual_fill_price <= 0" in text
