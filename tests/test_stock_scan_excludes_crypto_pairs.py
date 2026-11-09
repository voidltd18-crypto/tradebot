"""Regression coverage: crypto pairs must never reach the stock quote scan.

Static source checks avoid loading the live broker application.
"""
import ast
from pathlib import Path

SOURCE = Path("backend/legacy/monolith.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def test_adaptive_stock_rows_exclude_crypto_pairs_preserving_held_rows():
    refresh = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "refresh_adaptive_universe")
    add_row = next(n for n in refresh.body if isinstance(n, ast.FunctionDef) and n.name == "add_row")
    body = ast.get_source_segment(SOURCE, add_row)
    assert 'source != "HELD" and "/" in sym' in body
    assert 'item["symbol"] = sym' in body


def test_live_stock_scan_filters_slash_symbols_but_retains_broad_universe():
    loop = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "run_bot_loop")
    body = ast.get_source_segment(SOURCE, loop)
    assert 'if "/" not in str(sym)' in body
    assert "else list(current_universe)" in body
    assert "scan = compute_scan(symbol)" in body


def test_buy_pause_and_exit_management_preserved():
    assert 'TRADEBOT_STOCK_BUYS_PAUSED = os.getenv' in SOURCE
    assert "if TRADEBOT_STOCK_BUYS_PAUSED:" in SOURCE
    assert "manage_money_mode_positions()" in SOURCE
    assert "MARA_DAILY_ENTRY_LIMIT = 1" in SOURCE
