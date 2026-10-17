"""Regression checks for V19 daily-entry policy without starting live services."""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"
source = SOURCE.read_text(encoding="utf-8")
tree = ast.parse(source)
functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
assignments = {target.id: node.value for node in tree.body if isinstance(node, ast.Assign) for target in node.targets if isinstance(target, ast.Name)}

def function_text(name):
    return ast.get_source_segment(source, functions[name])

def test_first_dibs_disabled():
    assert isinstance(assignments["FIRST_DIBS_ENABLED"], ast.Constant)
    assert assignments["FIRST_DIBS_ENABLED"].value is False

def test_mara_limit_is_one():
    assert ast.literal_eval(assignments["MARA_DAILY_ENTRY_LIMIT"]) == 1
    assert "return MARA_DAILY_ENTRY_LIMIT" in function_text("daily_symbol_entry_limit")

def test_daily_lock_applies_to_every_symbol():
    text = function_text("is_locked_today")
    assert "today_symbol_buy_count(sym) >= 1" in text
    assert 'sym == "MARA"' not in text
    text = function_text("can_buy_symbol")
    assert "today_symbol_buy_count(sym) >= 1" in text
    assert 'sym == "MARA"' not in text

def test_no_mara_unlock_on_sell_or_restart():
    assert 'locked_today.pop(sym, None)' not in function_text("lock_symbol_until_tomorrow")
    assert 'locked_today.pop(symbol, None)' not in function_text("restore_today_sell_locks_from_db")

def test_profit_protection_can_pass_soft_pdt_guard():
    text = function_text("pdt_aware_should_avoid_sell")
    assert 'pnl_pct > 0' in text
    assert '"TRAILING" in reason_upper' in text
    assert '"PROFIT" in reason_upper' in text
    assert "broker remains authoritative" in text.lower()


if __name__ == "__main__":
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            func()
            print("PASS", name)
