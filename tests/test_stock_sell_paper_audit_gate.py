"""Verify stock recovery paper startup remains opt-in and read-only.

Tests source AST without importing backend.main (which imports live monolith).
"""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "backend/main.py"


def _function(name):
    root = ast.parse(SOURCE.read_text(encoding="utf-8"))
    return next(n for n in root.body if isinstance(n, ast.FunctionDef) and n.name == name)


def test_startup_returns_immediately_when_flag_disabled():
    node = _function("audit_pending_stock_sells_on_paper_startup")
    first = node.body[0]
    assert isinstance(first, ast.If)
    assert isinstance(first.test, ast.UnaryOp)
    assert isinstance(first.test.op, ast.Not)
    assert isinstance(first.body[0], ast.Return)
    assert ast.unparse(first.test.operand) == "_stock_sell_recovery_paper_audit_enabled()"


def test_paper_only_guard_precedes_broker_construction():
    node = _function("_stock_sell_recovery_paper_audit")
    source = ast.unparse(node)
    guard = source.index("if _legacy.PAPER is not True:")
    broker = source.index("make_paper_broker(")
    return_index = source.index("return audit_stock_sell_recovery(")
    assert guard < broker < return_index
    assert "PAPER_ALPACA_API_KEY" in source
    assert "PAPER_ALPACA_SECRET_KEY" in source


def test_disabled_endpoint_does_not_create_client():
    node = _function("stock_sell_recovery_paper_audit_endpoint")
    assert "_legacy.verify_api_key(request)" in ast.unparse(node)
    first_if = next(n for n in node.body if isinstance(n, ast.If))
    assert ast.unparse(first_if.test) == "not _stock_sell_recovery_paper_audit_enabled()"
    returned = first_if.body[0]
    assert isinstance(returned, ast.Return)
    assert ast.literal_eval(returned.value)["ordersSubmitted"] == 0


def test_paper_audit_contains_no_broker_submission():
    p = Path(__file__).resolve().parents[1] / "backend/stock_sell_startup_audit.py"
    tree = ast.parse(p.read_text(encoding="utf-8"))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "submit_order" not in names
    assert "submit_sell" not in names
    assert "close_position" not in names
