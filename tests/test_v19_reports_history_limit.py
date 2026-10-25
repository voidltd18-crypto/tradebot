"""Protect full historical closed-trade coverage in the Reports API."""
import ast
from pathlib import Path


def test_reports_returns_full_loaded_closed_trades_without_200_row_truncation():
    tree = ast.parse(Path("backend/legacy/monolith.py").read_text(encoding="utf-8"))
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
              and node.name == "_build_reports_payload")
    source = ast.unparse(fn)
    assert "closed_trades_from_db(5000)" in source
    assert "'closedTrades': closed" in source
    assert "'closedTrades': closed[:200]" not in source
    assert "if isinstance(row, dict) and _safe_num(row.get('qty')) > 0" in source


def test_backend_closed_trades_query_orders_newest_and_allows_more_than_500():
    tree = ast.parse(Path("backend/legacy/monolith.py").read_text(encoding="utf-8"))
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
              and node.name == "closed_trades_from_db")
    assert fn.args.defaults and isinstance(fn.args.defaults[0], ast.Constant)
    assert fn.args.defaults[0].value >= 1000
    assert "ORDER BY timestamp DESC" in ast.unparse(fn)
