"""Read-only diagnostic instrumentation safety checks."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"

def test_full_market_filter_diagnostics_are_aggregate_only():
    source = SRC.read_text(encoding="utf-8")
    fn = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)
              and node.name == "_full_market_scan")
    body = ast.get_source_segment(source, fn)
    for key in ('"snapshots"', '"bad_data"', '"price_volume"', '"spread"', '"accepted"'):
        assert key in body
    assert "FULL MARKET FILTER DIAG" in body
    assert "DYNAMIC_MARKET_MIN_VOLUME" in body
    assert "DYNAMIC_MARKET_MAX_SPREAD" in body
