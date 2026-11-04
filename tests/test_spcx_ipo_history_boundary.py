"""SpaceX SPCX 2026-06-12 IPO boundary: fail closed on reused ticker history.

Static extraction intentionally avoids importing live broker application.
"""
import ast
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

SOURCE = Path("backend/legacy/monolith.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def test_ipo_date_and_history_paths():
    assert 'SPCX_SPACEX_IPO_UTC = "2026-06-12T00:00:00+00:00"' in SOURCE
    assert SOURCE.count("d.symbol!='SPCX' OR d.timestamp>=?") >= 2
    assert "symbol!='SPCX' OR timestamp>=?" in SOURCE
    assert "spcx_pre_ipo_history_excluded" in SOURCE


def test_historical_checkpoint_refuses_old_spcx_without_requesting_broker_data():
    func = next(n for n in TREE.body if isinstance(n, ast.FunctionDef)
                and n.name == "_v6_historical_checkpoint_price")
    module = ast.Module(body=[func], type_ignores=[])
    ast.fix_missing_locations(module)

    calls = []
    class Broker:
        def get_stock_bars(self, request):
            calls.append(request)
            raise AssertionError("No historical request should occur")

    env = {
        "Any": Any, "Dict": Dict, "datetime": datetime, "timezone": timezone,
        "SPCX_SPACEX_IPO_UTC": "2026-06-12T00:00:00+00:00",
        "data_client": Broker(),
        "_v6_parse_utc": lambda value: datetime.fromisoformat(str(value).replace("Z", "+00:00")),
    }
    exec(compile(module, "<isolated_historical_checkpoint>", "exec"), env)
    try:
        env["_v6_historical_checkpoint_price"]("SPCX", "2026-06-11T18:00:00+00:00")
    except RuntimeError as exc:
        assert str(exc) == "spcx_pre_ipo_history_excluded"
    else:
        raise AssertionError("Old SPCX ETF history was accepted")
    assert calls == []


def test_sqlite_evidence_boundary_excludes_old_spcx_only():
    import sqlite3
    db = sqlite3.connect(":memory:")
    db.execute("create table history (symbol text, timestamp text)")
    db.executemany("insert into history values (?,?)", [
        ("SPCX", "2026-05-05T12:00:00+00:00"),
        ("SPCX", "2026-06-12T15:00:00+00:00"),
        ("TSLA", "2026-05-05T12:00:00+00:00"),
    ])
    rows = db.execute(
        "select symbol,timestamp from history where (symbol!='SPCX' or timestamp>=?) order by symbol,timestamp",
        ("2026-06-12T00:00:00+00:00",),
    ).fetchall()
    assert rows == [
        ("SPCX", "2026-06-12T15:00:00+00:00"),
        ("TSLA", "2026-05-05T12:00:00+00:00"),
    ]


def test_stock_buy_pause_retained():
    assert 'TRADEBOT_STOCK_BUYS_PAUSED", "true"' in SOURCE
    assert 'TRADEBOT_TWO_STOCK_MODE", "true"' in SOURCE
    assert "manage_money_mode_positions()" in SOURCE
