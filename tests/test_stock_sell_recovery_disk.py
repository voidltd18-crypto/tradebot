"""Shared persistent-disk SQLite journal tests; never access live Render."""
import sqlite3
import pytest

from backend.stock_sell_recovery_disk import open_recovery_on_tradebot_disk


def test_existing_tradebot_db_keeps_other_tables_and_durable_sell_reservation(tmp_path):
    mount = tmp_path / "var-data"
    mount.mkdir()
    path = mount / "trades.db"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT)")
        db.execute("INSERT INTO trades(symbol) VALUES ('FMC')")
    journal = open_recovery_on_tradebot_disk(path, mount_path=mount)
    journal.reserve_before_submit("FMC", "lot-1", "attempt-1", 10)
    journal.mark_unknown("FMC", "lot-1")
    recovered = open_recovery_on_tradebot_disk(path, mount_path=mount)
    assert recovered.snapshot("FMC", "lot-1")["status"] == "UNKNOWN"
    assert not recovered.reserve_before_submit("FMC", "lot-1", "duplicate", 10)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT symbol FROM trades").fetchone()[0] == "FMC"
        assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_does_not_create_database_on_unverified_mount(tmp_path):
    mount = tmp_path / "disk"
    mount.mkdir()
    path = mount / "missing.db"
    with pytest.raises(FileNotFoundError):
        open_recovery_on_tradebot_disk(path, mount_path=mount)
    assert not path.exists()


def test_refuses_database_outside_mount(tmp_path):
    mount = tmp_path / "disk"
    mount.mkdir()
    outside = tmp_path / "trades.db"
    sqlite3.connect(outside).close()
    with pytest.raises(ValueError, match="outside"):
        open_recovery_on_tradebot_disk(outside, mount_path=mount)


def test_refuses_symlinked_database_path(tmp_path):
    mount = tmp_path / "disk"
    mount.mkdir()
    actual = mount / "real.db"
    sqlite3.connect(actual).close()
    link = mount / "link.db"
    link.symlink_to(actual)
    with pytest.raises(ValueError, match="symlink"):
        open_recovery_on_tradebot_disk(link, mount_path=mount)
