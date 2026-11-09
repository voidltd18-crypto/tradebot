"""Regression: a historical reputation cooldown must not trap the approved two-stock universe."""
import ast
from pathlib import Path
from typing import Any, Dict, Tuple

SOURCE = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"


def _load_gate(*, two_stock_mode=True):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "symbol_reputation_allows_live_buy")
    module = ast.Module(body=[fn], type_ignores=[])
    ast.fix_missing_locations(module)
    hits = []
    namespace = {
        "Tuple": Tuple, "Dict": Dict, "Any": Any,
        "TRADEBOT_TWO_STOCK_MODE": two_stock_mode,
        "TRADEBOT_TWO_STOCK_SYMBOLS": frozenset(("TSLA", "SPCX")),
        "SYMBOL_REPUTATION_ENABLED": True,
        "_symbol_reputation_active_cooldown": lambda symbol: (
            hits.append(symbol) or {"expires_at": "2026-11-14T14:30:25+00:00", "score": 10}
        ),
    }
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace["symbol_reputation_allows_live_buy"], hits


def test_tsla_spcx_ignore_legacy_cooldown_only_when_two_stock_mode_active():
    gate, queried = _load_gate(two_stock_mode=True)
    for symbol in ("TSLA", "SPCX"):
        permitted, reason, details = gate(symbol)
        assert permitted and details["symbol"] == symbol
        assert details["legacyReputationVeto"] is False
        assert "legacy reputation veto bypassed" in reason
    assert queried == []  # no historical DB reputation lookup needed


def test_other_stocks_retain_reputation_cooldown():
    gate, queried = _load_gate(two_stock_mode=True)
    permitted, _, _ = gate("MARA")
    assert not permitted
    assert queried == ["MARA"]


def test_normal_mode_still_enforces_reputation_cooldown_for_tsla():
    gate, queried = _load_gate(two_stock_mode=False)
    permitted, _, _ = gate("TSLA")
    assert not permitted
    assert queried == ["TSLA"]


def test_other_live_stock_safeguards_still_present():
    source = SOURCE.read_text(encoding="utf-8")
    assert "can_buy, reason = can_buy_symbol(symbol)" in source
    assert "if PDT_AWARE_MODE_ENABLED and today_buy_count()" in source
    assert "sniper_ok, sniper_reason = sniper_passes(scan)" in source
    assert "aplus_ok, aplus_reason = a_plus_gate(scan)" in source
    assert "if not scan[\"ready_to_buy\"]:" in source
    assert "v17_v2_trade_gate_with_cold_start(scan" in source
    assert "broker_asset = check_from_broker(trading_client, symbol)" in source
