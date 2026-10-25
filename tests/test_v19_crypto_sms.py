import os
import pytest
from backend.v19_crypto_sms import format_crypto_alert, send_crypto_sms


def test_profit_trigger_is_not_claimed_as_confirmed_sale():
    result = format_crypto_alert("PROFIT_EXIT_TRIGGER", "SOLUSD", 2.25, 104)
    assert "No confirmed sale yet" in result
    assert "TradeBot SOLUSD" in result


def test_losses_remain_under_manual_control():
    assert "manual control only" in format_crypto_alert("LOSS_MANUAL_ONLY", "SOLUSD", -3)


def test_unrecognized_event_rejected():
    with pytest.raises(ValueError):
        format_crypto_alert("SELL_SUBMITTED", "SOLUSD")


def test_sms_disabled_by_default(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    assert send_crypto_sms("test") == {"sent": False, "reason": "disabled"}


def test_missing_credentials_do_not_send(monkeypatch):
    for key in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "TRADEBOT_SMS_TO_NUMBER"):
        monkeypatch.delenv(key, raising=False)
    assert send_crypto_sms("test", enabled=True)["sent"] is False
