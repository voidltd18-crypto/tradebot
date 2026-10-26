import sqlite3
from pathlib import Path
from backend.v19_crypto_profit_sell_executor import _heartbeat_path, _record_poll, worker_health


def test_status_uses_separate_database(tmp_path):
    trading=str(tmp_path/"trades.sqlite")
    health=_heartbeat_path(trading)
    assert health != trading
    _record_poll(trading,result={"submitted":[],"blocked":[("XRPUSD","live bid below target")]})
    assert Path(health).exists()
    assert not Path(trading).exists()
    assert worker_health(trading)["lastPoll"]["blockedCount"]==1


def test_busy_trading_database_does_not_block_worker_heartbeat(tmp_path):
    trading=str(tmp_path/"trades.sqlite")
    conn=sqlite3.connect(trading)
    conn.execute("CREATE TABLE busy(id INTEGER)")
    conn.execute("BEGIN EXCLUSIVE")
    try:
        _record_poll(trading,result={"submitted":["XRPUSD"],"blocked":[]})
        assert worker_health(trading)["lastPoll"]["submittedCount"]==1
    finally:
        conn.rollback()
        conn.close()
