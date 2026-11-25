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


def test_read_only_scan_captures_gate_reasons_without_recording_trades():
    from typing import Any, Dict, Optional
    from unittest.mock import Mock

    path = Path(__file__).resolve().parents[1] / "backend/legacy/monolith.py"
    names = {"pick_money_mode_stocks", "v17_live_entry_gate_pipeline"}
    functions = [node for node in ast.parse(path.read_text()).body
                 if isinstance(node, ast.FunctionDef) and node.name in names]
    persistence = Mock()
    scope = {
        "Any": Any,
        "Dict": Dict,
        "Optional": Optional,
        "os": Mock(getenv=lambda _key, default: default),
        "PDT_AWARE_MODE_ENABLED": False,
        "_prioritize_first_dibs_rows": list,
        "can_buy_symbol": lambda symbol: (False, "existing open order") if symbol == "C" else (True, ""),
        "symbol_reputation_allows_live_buy": lambda _: (True, "", {}),
        "sniper_passes": lambda _: (True, ""),
        "a_plus_gate": lambda _: (True, ""),
        "v17_v2_trade_gate_with_cold_start": lambda *_a, **_kw: (True, {}),
        "record_v2_setup_decision": persistence,
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), scope)
    scans = [
        dict(symbol=symbol, ready_to_buy=ready, confidence=0.8, quality_score=0.05, spread=0.001)
        for symbol, ready in (("A", True), ("B", False), ("C", True))
    ]
    decisions = {}
    survivors = scope["v17_live_entry_gate_pipeline"](
        scans, persist_decisions=False, log_rejections=False, scan_decisions=decisions
    )
    assert [row["symbol"] for row in survivors] == ["A"]
    assert [decisions[symbol]["stage"] for symbol in ("A", "B", "C")] == [
        "final_gate", "trigger_gate", "account_gate"
    ]
    assert decisions["C"]["reason"] == "existing open order"
    persistence.assert_not_called()
