import sqlite3
from backend.analysis.quality_forward_outcomes import analyse

def test_quality_forward_analysis_keeps_horizons_separate():
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE v179_decision_audit (
        quality REAL, return_pct REAL, due_minutes INTEGER,
        decision_id INTEGER, status TEXT)""")
    rows = [(0.02, -2.0, 15, 1, "COMPLETED"),
            (0.04, 1.0, 15, 2, "COMPLETED"),
            (0.11, 3.0, 15, 3, "COMPLETED"),
            (0.11, -1.0, 60, 3, "COMPLETED"),
            (0.11, 100.0, 15, 4, "PENDING")]
    conn.executemany("INSERT INTO v179_decision_audit VALUES (?,?,?,?,?)", rows)
    result = analyse(conn)
    assert result["ok"]
    assert len(result["groups"]) == 4
    assert sum(x["samples"] for x in result["groups"]) == 4
    assert "NOT realised trade P&L" in result["measurement"]
    assert analyse(conn, 15)["groups"][2]["meanForwardReturnPct"] == 3.0

def test_absent_table_reported_without_mutating_database():
    conn = sqlite3.connect(":memory:")
    assert analyse(conn)["ok"] is False
