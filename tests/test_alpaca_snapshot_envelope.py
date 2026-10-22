"""Regression check for Alpaca full-market snapshot response decoding."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"

def test_direct_symbol_mapping_supported():
    src = SRC.read_text(encoding="utf-8")
    ast.parse(src)
    fn = next(x for x in ast.parse(src).body if isinstance(x, ast.FunctionDef) and x.name == "_full_market_scan")
    body = ast.get_source_segment(src, fn)
    assert 'payload.get("snapshots", payload)' in body
    direct = {"AAPL": {"dailyBar": {"c": 150.0, "v": 1000000}}}
    wrapped = {"snapshots": direct}
    decode = lambda p: p.get("snapshots", p) if isinstance(p, dict) else {}
    assert decode(direct) == direct
    assert decode(wrapped) == direct
    assert decode([]) == {}
