import ast
from pathlib import Path

def test_quality_outcomes_route_restricts_horizons_and_is_read_only():
    src = (Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py").read_text()
    tree = ast.parse(src)
    fn = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == "api_v179_quality_outcomes")
    body = ast.get_source_segment(src, fn)
    assert 'horizon not in (15, 30, 60, 120)' in body
    assert 'analyse(conn, horizon)' in body
    assert 'return {"ok": False' in body
    assert 'submit_order' not in body
    assert 'market_buy' not in body
    assert "UPDATE " not in body
