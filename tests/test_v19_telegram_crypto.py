import json
from backend.v19_telegram_crypto import send_telegram_crypto_alert, telegram_configured


def test_disabled_by_default(monkeypatch):
    monkeypatch.setenv("TRADEBOT_TELEGRAM_BOT_TOKEN", "secret")
    monkeypatch.setenv("TRADEBOT_TELEGRAM_CHAT_ID", "123")
    assert send_telegram_crypto_alert("Profit") == {"sent": False, "reason": "disabled"}


def test_missing_config_fails_closed(monkeypatch):
    monkeypatch.delenv("TRADEBOT_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TRADEBOT_TELEGRAM_CHAT_ID", raising=False)
    assert telegram_configured() is False
    assert send_telegram_crypto_alert("Profit", enabled=True)["sent"] is False


def test_message_sent_with_mocked_transport(monkeypatch):
    monkeypatch.setenv("TRADEBOT_TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TRADEBOT_TELEGRAM_CHAT_ID", "123")
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return json.dumps({"ok": True}).encode()
    def open_url(req, timeout):
        assert timeout == 10
        body = json.loads(req.data)
        assert body["chat_id"] == "123"
        assert body["text"] == "SOL profit detected"
        return Response()
    assert send_telegram_crypto_alert("SOL profit detected", enabled=True, opener=open_url)["sent"] is True


def test_rejection_does_not_raise_or_trigger_trade(monkeypatch):
    monkeypatch.setenv("TRADEBOT_TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TRADEBOT_TELEGRAM_CHAT_ID", "123")
    def broken(*args, **kwargs):
        raise RuntimeError("private data")
    assert send_telegram_crypto_alert("SOL", enabled=True, opener=broken) == {
        "sent": False, "reason": "telegram_transport_failed"}
