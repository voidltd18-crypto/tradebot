from backend.v19_crypto_profit_sell_executor import worker_health, _record_poll


def test_health_is_persisted_and_read_only(tmp_path, monkeypatch):
    path = str(tmp_path / "status.sqlite")
    monkeypatch.setenv("TRADEBOT_CRYPTO_PROFIT_SELL_ENABLED", "true")
    monkeypatch.setenv("TRADEBOT_CRYPTO_PROFIT_SELL_LIVE_APPROVED", "true")
    assert worker_health(path)["lastPoll"] is None
    _record_poll(path, result={"blocked":[("XRPUSD", "live bid below target")],
                               "submitted":[]})
    status = worker_health(path)
    assert status["enabled"] is True
    assert status["lastPoll"]["outcome"] == "completed"
    assert status["lastPoll"]["blockedCount"] == 1
    assert status["lastPoll"]["submittedCount"] == 0


def test_worker_errors_are_visible(tmp_path):
    path = str(tmp_path / "status.sqlite")
    _record_poll(path, error="ConnectionError")
    assert worker_health(path)["lastPoll"]["outcome"] == "error"
    assert worker_health(path)["lastPoll"]["detail"] == "ConnectionError"
