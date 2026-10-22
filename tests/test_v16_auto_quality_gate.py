"""Check independent V16 quality rejection before score approval and allocation."""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"


def test_auto_quality_veto_runs_before_score_acceptance():
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build_v16_portfolio_plan")
    text = ast.get_source_segment(source, fn)
    assert 'reasonCode": "QUALITY_BELOW_MINIMUM"' in text
    assert "not manual and (not math.isfinite(quality) or quality < V16_AUTO_MIN_ENTRY_QUALITY)" in text
    assert text.index('"QUALITY_BELOW_MINIMUM"') < text.index("if score < effective_minimum_score")
    assert text.index('"QUALITY_BELOW_MINIMUM"') < text.index("ranked.append(item)")


def test_auto_quality_default_rejects_mara_sample():
    import re
    source = SOURCE.read_text(encoding="utf-8")
    floor = float(re.search(r'TRADEBOT_V16_AUTO_MIN_ENTRY_QUALITY", "([0-9.]+)"', source).group(1))
    assert 0.0433 < floor
    assert floor == 0.10
