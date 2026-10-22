"""Verify crypto pairs are not eligible for the stock-only adaptive scan."""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"

def test_crypto_pair_gate():
    src = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "_adaptive_symbol_buy_allowed")
    body = ast.get_source_segment(src, fn)
    assert '"/" in sym' in body

def test_stock_entry_protections_remain():
    src = SOURCE.read_text(encoding="utf-8")
    for rule in ("if not sniper_ok:", "if not aplus_ok:", "if not reputation_ok:", "QUALITY_BELOW_MINIMUM"):
        assert rule in src
