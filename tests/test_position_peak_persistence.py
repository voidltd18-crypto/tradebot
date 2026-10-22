"""Regression tests for restart-safe position peak persistence."""
import ast
import sqlite3
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"


def get_peak_function(tmp_path):
    src = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "_persistent_position_peak")
    module = ast.Module(body=[fn], type_ignores=[])
    ast.fix_missing_locations(module)
    path = tmp_path / "positions.db"
    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    ns = {"SQLITE_ENABLED": True, "db_connect": connect}
    exec(compile(module, str(SOURCE), "exec"), ns)
    return ns["_persistent_position_peak"]


def test_peak_survives_restart(tmp_path):
    peak = get_peak_function(tmp_path)
    assert peak("FLNC", 5.87, 5.96) == 5.96
    # Simulated restart: new function namespace, same database file.
    recovered = get_peak_function(tmp_path)
    assert recovered("FLNC", 5.87, 5.83) == 5.96


def test_new_entry_resets_old_peak(tmp_path):
    peak = get_peak_function(tmp_path)
    peak("FLNC", 5.87, 5.96)
    assert peak("FLNC", 5.50, 5.54) == 5.54


def test_current_peak_only_moves_up(tmp_path):
    peak = get_peak_function(tmp_path)
    peak("FLNC", 5.87, 5.93)
    assert peak("FLNC", 5.87, 5.96) == 5.96
    assert peak("FLNC", 5.87, 5.90) == 5.96
