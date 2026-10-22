"""Ensure UI trailing armed flag tracks high-water mark, not latest quote."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"

def test_trailing_armed_uses_peak():
    src = SRC.read_text()
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "get_all_positions")
    code = ast.get_source_segment(src, fn)
    assert 'trailing_active = bool((state[symbol].get("highest_since_entry") or 0.0) >= trail_start_price)' in code
    assert 'trailing_active = quote_price >= trail_start_price' not in code

def test_exit_logs_runner_block_reason():
    src = SRC.read_text()
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "manage_money_mode_positions")
    code = ast.get_source_segment(src, fn)
    assert "status=RUNNER_GRACE" in code
    assert "status=ARMED_PULLED_BACK" in code
