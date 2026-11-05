"""Isolated tests for issuer-safe SPCX evidence in V4/V10/V11 and quote bars."""
import ast
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

SOURCE = Path("backend/legacy/monolith.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
IPO = "2026-06-12T00:00:00+00:00"


def extract(name, env):
    node = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(module, "isolated_monolith", "exec"), env)
    return env[name]


def valid(symbol, timestamp):
    return symbol != "SPCX" or bool(timestamp and str(timestamp)[:10] >= "2026-06-12")


def test_issuer_filter_missing_and_earlier_dates():
    fn = extract("spcx_evidence_valid", {"Any": Any})
    assert not fn("SPCX", None)
    assert not fn("SPCX", "2026-06-11T23:59:00+00:00")
    assert fn("SPCX", "2026-06-12T13:00:00+00:00")
    assert fn("TSLA", "2010-01-01")
    assert fn("AAPL", None)


def test_v4_contextual_matches_dont_use_old_etf_evidence():
    env = {"List": List, "Dict": Dict, "Any": Any, "math": math,
           "spcx_evidence_valid": valid}
    rank = extract("_v4_rank_contextual_rows", env)
    target = dict(symbol="TSLA", confidence=0.7, weekday=3)
    rows = [
        dict(symbol="SPCX", observed_at="2026-05-01T12:00:00+00:00", confidence=0.7),
        dict(symbol="SPCX", observed_at="2026-06-15T12:00:00+00:00", confidence=0.7),
        dict(symbol="TSLA", observed_at="2026-05-01T12:00:00+00:00", confidence=0.7),
    ]
    result = rank(rows, target)
    assert len(result) == 2
    assert not any(r["symbol"] == "SPCX" and r["observed_at"].startswith("2026-05") for r in result)


def test_v10_and_v11_observation_reader_excludes_preipo():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE v9_market_memory (decision_id INTEGER, symbol TEXT, observed_at TEXT)")
    db.execute("CREATE TABLE v10_evidence_lineage (snapshot_id INTEGER, horizon_hours INTEGER, outcome_status TEXT, net_return_pct REAL)")
    db.executemany("INSERT INTO v9_market_memory VALUES (?,?,?)", [
        (1, "SPCX", "2026-05-05T12:00:00+00:00"),
        (2, "SPCX", "2026-06-15T12:00:00+00:00"),
        (3, "TSLA", "2026-05-05T12:00:00+00:00"),
    ])
    db.executemany("INSERT INTO v10_evidence_lineage VALUES (?,24,'COMPLETE',1.5)", [(1,), (2,), (3,)])
    env = {"List": List, "Dict": Dict, "Any": Any, "spcx_evidence_valid": valid}
    reader = extract("_v10_load_observations", env)
    rows = reader(db, 24)
    assert {(r["symbol"], r["observed_at"][:10]) for r in rows} == {
        ("SPCX", "2026-06-15"), ("TSLA", "2026-05-05")
    }


def test_v91_spacex_bars_clamp_request_and_ignore_etf_returns():
    day_before = datetime(2026, 6, 11, 12, tzinfo=timezone.utc)
    day_after = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    calls = []
    class FakeClient:
        def get_stock_bars(self, request):
            calls.append(request)
            return {"SPCX": [SimpleNamespace(timestamp=day_before), SimpleNamespace(timestamp=day_after)]}
    env = {
        "Any": Any, "List": List,
        "datetime": datetime, "SPCX_SPACEX_IPO_UTC": IPO,
        "StockBarsRequest": lambda **kwargs: kwargs,
        "DataFeed": SimpleNamespace(IEX="IEX"),
        "data_client": FakeClient(),
        "_v6_parse_utc": lambda v: v,
    }
    bars = extract("_v91_bars", env)(
        "SPCX", "DAY", datetime(2026, 5, 1, tzinfo=timezone.utc), datetime(2026, 6, 20, tzinfo=timezone.utc)
    )
    assert len(bars) == 1 and bars[0].timestamp == day_after
    assert calls[0]["start"] >= datetime.fromisoformat(IPO)


def test_advisory_reports_and_replay_are_guarded():
    assert SOURCE.count("spcx_evidence_valid(") >= 5
    assert "TRADEBOT_STOCK_BUYS_PAUSED" in SOURCE
