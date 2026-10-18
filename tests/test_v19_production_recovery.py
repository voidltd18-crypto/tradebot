"""Non-trading V19 checks for production-based historical outcome recovery."""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"
text = SOURCE.read_text(encoding="utf-8")
tree = ast.parse(text)

def body(name):
    fn = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return ast.get_source_segment(text, fn)

def test_historical_lookup_separate_from_write():
    writer = body("_v6_write_historical_outcome")
    evaluator = body("v2_evaluate_due_outcomes")
    assert "if checkpoint is None:" in writer
    assert "checkpoint_data = _v6_historical_checkpoint_price(" in evaluator
    assert evaluator.index("checkpoint_data = _v6_historical_checkpoint_price(") < evaluator.index("_v6_write_historical_outcome(conn,row,checkpoint_data)")
    assert "conn.rollback()" in evaluator
    assert "conn.commit()" in evaluator

def test_live_accounting_and_mara_guards_preserved():
    assert "MARA_DAILY_ENTRY_LIMIT" in text
    assert "FIRST_DIBS_ENABLED" in text
    assert "_release_transient_memory" in text

def test_mara_single_entry_and_sell_lock():
    buy = body("can_buy_symbol")
    locked = body("is_locked_today")
    assert "today_symbol_buy_count(sym) >= MARA_DAILY_ENTRY_LIMIT" in buy
    assert "today_symbol_buy_count(sym) >= 1" in locked
    assert "MARA_DAILY_ENTRY_LIMIT = 1" in text


if __name__ == "__main__":
    test_historical_lookup_separate_from_write()
    test_live_accounting_and_mara_guards_preserved()
    test_mara_single_entry_and_sell_lock()
    print("V19 production-based checks passed")
