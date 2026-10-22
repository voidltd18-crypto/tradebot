"""Regression checks for bounded fallback rotation."""
import ast
from pathlib import Path

P = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"

def test_rotation_changes_fallback_order_only():
    src = P.read_text()
    ast.parse(src)
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_adaptive_discovery_rows")
    body = ast.get_source_segment(src, fn)
    assert 'r.get("source") in ("fallback", "broad-fallback")' in body
    assert "ADAPTIVE_UNIVERSE_REFRESH_SECONDS" in body
    assert "return primary + fallback" in body

def test_live_gates_remain():
    src = P.read_text()
    for token in ["if not sniper_ok:", "if not aplus_ok:", "if not reputation_ok:", "if not v2_ok:", "QUALITY_BELOW_MINIMUM"]:
        assert token in src
