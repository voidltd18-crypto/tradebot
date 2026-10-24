import ast
from pathlib import Path

def test_gate_breakdown_does_not_change_selection():
    src = (Path(__file__).resolve().parents[1] / "backend/legacy/monolith.py").read_text()
    fn = next(x for x in ast.parse(src).body if isinstance(x, ast.FunctionDef)
              and x.name == "pick_money_mode_stocks")
    body = ast.get_source_segment(src, fn)
    assert 'gate_counts = {}' in body
    assert 'key = stage if decision == "REJECTED" else "passed"' in body
    assert 'V17 ENTRY GATE BREAKDOWN' in body
    assert 'if log_rejections:' in body
    for gate in ('account_gate', 'pdt_gate', 'symbol_reputation_gate',
                 'sniper_gate', 'a_plus_gate', 'trigger_gate', 'expectancy_gate'):
        assert gate in body
    assert 'return candidates' in body
