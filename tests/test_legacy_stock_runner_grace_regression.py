"""Isolated runtime regression of the REAL legacy stock runner decision.

Extracts just one AST function from monolith.py; never imports or starts
the trading engine and never connects to any broker or secrets.
"""
import ast
from pathlib import Path
from typing import Any, Dict

import pytest


SRC = Path(__file__).resolve().parents[1] / "backend/legacy/monolith.py"


def load_runner(*, enabled=True, checks=2, short_momentum=0.0):
    root = ast.parse(SRC.read_text(encoding="utf-8"))
    node = next(n for n in root.body
                if isinstance(n, ast.FunctionDef)
                and n.name == "_v17_runner_trail_decision")
    state = {}
    def get_state(symbol):
        return state.setdefault(symbol, {})
    def reset(symbol):
        state.pop(symbol, None)
    ctx = {
        "Dict": Dict, "Any": Any,
        "_v17_runner_trail_state": get_state,
        "_v17_reset_runner_trail": reset,
        "compute_short_momentum": lambda symbol, price: short_momentum,
        "ADAPTIVE_RUNNER_TRAIL_ENABLED": enabled,
        "ADAPTIVE_RUNNER_MIN_CURRENT_PNL_PCT": 0.5,
        "ADAPTIVE_RUNNER_MIN_PEAK_PNL_PCT": 1.5,
        "ADAPTIVE_RUNNER_MAX_SHALLOW_BREACH_PCT": 0.15,
        "ADAPTIVE_RUNNER_MAX_NEGATIVE_MOMENTUM": -0.01,
        "ADAPTIVE_RUNNER_CONFIRMATION_CHECKS": checks,
    }
    isolated = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(isolated, str(SRC), "exec"), ctx)
    return ctx["_v17_runner_trail_decision"], state


def position(price=101.9):
    return {"symbol": "FMC", "entry": 100, "highest": 103,
            "price": price, "pnlPct": price - 100}


def test_runner_one_shallow_grace_then_confirmed_exit():
    decision, state = load_runner(checks=2)
    first = decision(position(), 102)
    assert first["grace"] and not first["sell"]
    assert state["FMC"]["runner_trail_breach_count"] == 1
    second = decision(position(), 102)
    assert second["sell"] and not second["grace"]
    assert "FMC" not in state


def test_recovery_clears_pending_runner_grace():
    decision, state = load_runner(checks=2)
    assert decision(position(), 102)["grace"]
    assert not decision(position(102.2), 102)["sell"]
    assert "FMC" not in state
    assert decision(position(), 102)["grace"]


def test_deep_breach_sells_without_grace():
    decision, _ = load_runner(checks=2)
    result = decision(position(101.4), 102)
    assert result["sell"] and not result["grace"]


def test_momentum_collapse_sells_without_grace():
    decision, _ = load_runner(checks=2, short_momentum=-0.1)
    assert decision(position(), 102)["sell"]


def test_disabled_runner_does_not_delay_floor_exit():
    decision, _ = load_runner(enabled=False)
    assert decision(position(), 102)["sell"]


def test_missing_profit_sells_without_grace():
    decision, _ = load_runner()
    p = position(99.9)
    assert decision(p, 100)["sell"]
