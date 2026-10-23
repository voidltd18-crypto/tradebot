"""Static quality-calibration regression checks."""
import ast
from pathlib import Path

def test_quality_calibration_is_read_only():
    source = (Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py").read_text()
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build_v16_portfolio_plan")
    body = ast.get_source_segment(source, fn)
    assert "V16 QUALITY CALIBRATION" in body
    assert "median=" in body and "above_floor=" in body
    assert "QUALITY_BELOW_MINIMUM" in body
    assert "quality < V16_AUTO_MIN_ENTRY_QUALITY" in body
    assert 'os.getenv("TRADEBOT_V16_AUTO_MIN_ENTRY_QUALITY", "0.10")' in source
