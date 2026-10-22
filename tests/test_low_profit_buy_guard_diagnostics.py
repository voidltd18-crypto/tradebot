"""Regression checks for the read-only buy-guard diagnostic route."""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"


def _diagnostic():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
              and node.name == "low_profit_buy_guard_diagnostics")
    module = ast.Module(body=[fn], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "low_profit_buy_guard_status": lambda: {
            "enabled": True,
            "source": "verified_closed_trades",
            "weak": {"XYZ": {"trades": 5, "bestTradeGbp": 4.50}}},
        "SQLITE_ENABLED": True,
        "_LOW_PROFIT_GUARD_CACHE": {"verifiedSellOrders": 19},
    }
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace["low_profit_buy_guard_diagnostics"]()


def test_read_only_guard_diagnostics_reports_live_blocklist():
    result = _diagnostic()
    assert result["ok"] and result["readOnly"]
    assert result["enabled"] and result["sqliteEnabled"]
    assert result["verifiedSellOrdersAnalysed"] == 19
    assert result["excludedSymbolCount"] == 1
    assert result["excludedSymbols"] == [
        {"symbol": "XYZ", "trades": 5, "bestTradeGbp": 4.50}]
    assert result["rule"]["minimumVerifiedSellOrders"] == 5


def test_guard_uses_five_trades_in_live_execution_path():
    text = SOURCE.read_text(encoding="utf-8")
    assert "weak_symbols_by_realised_trades(rows, min_trades=5, profit_threshold_gbp=5.0)" in text
    assert 'eligible, block_reason = low_profit_buy_allowed(symbol)' in text
