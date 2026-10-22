import ast
from pathlib import Path

def test_alpaca_snapshot_response_diagnostic():
    source = (Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py").read_text()
    ast.parse(source)
    assert "FULL MARKET RESPONSE DIAG" in source
    assert "top_keys=" in source
    assert "snapshots_type=" in source
    assert "response.text" not in source[source.index('def _full_market_scan('):source.index('def refresh_dynamic_market_candidates(')]
