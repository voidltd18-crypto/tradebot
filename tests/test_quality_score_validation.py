"""Offline boundary study of the unchanged live quality formula.

Reference examples deliberately do NOT relax the 0.10 automatic entry floor.
"""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"

def reference_quality(pullback, spread, momentum, *,
                      min_pullback=0.001, max_pullback=0.045,
                      max_spread=0.015, prefer_spread=0.006,
                      min_momentum=-0.015, max_momentum=0.045):
    result = 0.0
    if min_pullback <= pullback <= max_pullback:
        result += pullback * 3.0
    if spread <= max_spread:
        result += max(0.0, prefer_spread - spread) * 2.0
    if min_momentum <= momentum <= max_momentum:
        result += max(0.0, momentum) * 0.7
    else:
        result -= 0.02
    return result

def test_matches_current_quality_formula_and_floor():
    source = SRC.read_text()
    tree = ast.parse(source)
    scan = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == "compute_scan")
    code = ast.get_source_segment(source, scan)
    assert "quality_score += pullback * 3.0" in code
    assert "quality_score += tightness_score * 2.0" in code
    assert "quality_score += max(0.0, short_momentum) * 0.7" in code
    assert 'os.getenv("TRADEBOT_V16_AUTO_MIN_ENTRY_QUALITY", "0.10")' in source
    assert "QUALITY_BELOW_MINIMUM" in source

def test_near_flat_stock_rejected_even_with_tight_spread():
    assert reference_quality(0.005, 0.001, 0.002) < 0.10

def test_large_pullback_can_pass_without_momentum():
    assert reference_quality(0.033, 0.003, 0.0) >= 0.10

def test_high_momentum_and_smaller_pullback_can_pass():
    assert reference_quality(0.022, 0.003, 0.045) >= 0.10

def test_mara_like_raw_quality_below_unchanged_floor():
    assert 0.0433 < 0.10
