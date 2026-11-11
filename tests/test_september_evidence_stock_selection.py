"""Verify archived September stock selection never admits a loser or unknown symbol.

No broker credentials, running bot, external requests, or orders are used.
"""
import ast
import math
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "backend/legacy/monolith.py"
SOURCE = FILE.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def isolate(name, namespace):
    fn = next(node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(FILE), "exec"), namespace)
    return namespace[name]


def closed(symbol, day, pnl, qty=1):
    return {"symbol": symbol, "day": day, "pnlGbp": pnl, "qty": qty}


def setup(rows, enabled=True):
    cache = {"at": 0.0, "symbols": (), "evidence": ()}
    ns = {
        "TRADEBOT_PERFORMANCE_UNIVERSE_MODE": enabled,
        "TRADEBOT_TWO_STOCK_MODE": True,
        "TRADEBOT_TWO_STOCK_SYMBOLS": frozenset(("TSLA", "SPCX")),
        "SEPTEMBER_STOCK_SELECTION_POOL": frozenset(("MARA", "TSLA", "NVDA", "SPCX")),
        "_SEPTEMBER_SELECTION_CACHE": cache,
        "closed_trades_from_db": lambda count: rows,
        "time": type("Clock", (), {"monotonic": staticmethod(lambda: 1000.0)}),
        "math": math,
        "TECH_GIANT_STOCK_ALLOWED": frozenset(("AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "ORCL", "AMD", "TSLA")),
    }
    qualify = isolate("september_qualified_stock_symbols", ns)
    allowed = isolate("two_stock_buy_allowed", ns)
    return qualify, allowed, cache


def test_archived_september_qualifier_is_independent_of_current_tech_allowlist():
    rows = [
        closed("MARA", "2026-09-03", 5),
        closed("MARA", "2026-09-04", -1),
        closed("NVDA", "2026-09-05", -3),
        closed("NVDA", "2026-09-07", 1),
        closed("TSLA", "2026-10-02", 100),
        closed("SPCX", "2026-09-03", 3),
        closed("BTCUSD", "2026-09-03", 200),
        closed("MARA", "2026-09-06", 50, qty=0),
    ]
    qualify, allowed, cache = setup(rows)
    assert qualify() == ["MARA"]
    assert not allowed("MARA")
    assert allowed("NVDA")
    assert allowed("TSLA")
    assert not allowed("SPCX")
    assert not allowed("BTCUSD")
    assert cache["evidence"][0][1]["pnlGbp"] == 4


def test_no_september_history_does_not_disable_current_tech_allowlist():
    qualify, allowed, _ = setup([])
    assert qualify() == []
    assert allowed("TSLA")
    assert not allowed("MARA")


def test_legacy_flag_does_not_override_current_tech_allowlist():
    _, allowed, _ = setup([], enabled=False)
    assert allowed("TSLA") and allowed("NVDA")
    assert not allowed("MARA") and not allowed("SPCX")


def test_pause_daily_lock_cap_and_execution_gates_remain_in_source():
    assert 'if TRADEBOT_STOCK_BUYS_PAUSED:' in SOURCE
    assert 'if not two_stock_buy_allowed(sym):' in SOURCE
    assert 'if not two_stock_buy_allowed(symbol):' in SOURCE
    assert 'MARA_DAILY_ENTRY_LIMIT = 1' in SOURCE
    assert 'if allowed_new_position_count() <= 0:' in SOURCE
    assert 'if emergency_stop:' in SOURCE
    assert 'manage_money_mode_positions()' in SOURCE
    assert 'v17_live_entry_gate_pipeline(' in SOURCE
