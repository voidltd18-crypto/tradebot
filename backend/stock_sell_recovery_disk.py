"""Fail-closed path selection for experimental stock sell journal.

NOT wired into the worker. The existing TradeBot SQLite database is already
configured to use the Render persistent disk by default. Reuse it only after
confirming the *effective* path is inside the mounted disk and an exclusive
writer owns the bot. This helper NEVER creates directories or database files.
"""
from pathlib import Path
from backend.stock_sell_recovery_journal import SellRecoveryJournal


def open_recovery_on_tradebot_disk(sqlite_database_file, *, mount_path="/var/data"):
    database = Path(sqlite_database_file).resolve(strict=True)
    mount = Path(mount_path).resolve(strict=True)
    if not mount.is_dir() or not database.is_file():
        raise ValueError("persistent Render mount and existing database required")
    if database == mount or mount not in database.parents:
        raise ValueError("live database is outside the verified persistent disk")
    if database.is_symlink():
        raise ValueError("symlink database not permitted")
    return SellRecoveryJournal(database)
