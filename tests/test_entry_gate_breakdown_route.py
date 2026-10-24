import ast
from pathlib import Path

def test_entry_gate_breakdown_read_only_and_bounded():
    source = (Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py").read_text()
    tree = ast.parse(source)
    fn = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == "api_v17_entry_gate_breakdown")
    code = ast.get_source_segment(source, fn)
    assert 'max(1, min(int(hours), 168))' in code
    assert "COUNT(DISTINCT symbol)" in code
    assert "SELECT MAX(id)" in code
    assert "byStage" in code and "latestBySymbol" in code
    assert "submit_order" not in code
    assert "UPDATE " not in code and "DELETE " not in code
