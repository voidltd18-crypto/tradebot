from datetime import datetime, timezone
from types import SimpleNamespace as N

from backend.v19_crypto_telegram_monitor import poll_crypto_alerts


class Broker:
    def __init__(self, positions=None, orders=None):
        self.positions = positions if positions is not None else []
        self.orders = orders if orders is not None else []
    def get_all_positions(self):
        return self.positions
    def get_orders(self, filter=None):
        return self.orders
    def get_asset(self, symbol):
        return N(asset_class="crypto" if symbol == "SOLUSD" else "us_equity")


def sol(price="102"):
    return N(symbol="SOLUSD", asset_class="crypto", qty="2", avg_entry_price="100", current_price=price)


def test_profit_once_persisted_across_cycles(tmp_path):
    messages = []
    def sender(message, *, enabled):
        messages.append(message)
        return {"sent": True}
    path = str(tmp_path / "alerts.db")
    broker = Broker([sol()])
    poll_crypto_alerts(broker, {}, path, sender=sender)
    poll_crypto_alerts(broker, {}, path, sender=sender)
    assert len(messages) == 1
    assert "PROFIT" in messages[0]
    assert "No sale executed" in messages[0]


def test_loss_never_alerts_exit(tmp_path):
    messages = []
    def sender(msg, *, enabled):
        messages.append(msg)
        return {"sent": True}
    poll_crypto_alerts(Broker([sol("95")]), {"SOLUSD": {"highest_since_entry": "110"}},
                       str(tmp_path / "alerts.db"), sender=sender)
    assert messages == []


def test_verified_peak_generates_advisory_signal(tmp_path):
    messages = []
    def sender(msg, *, enabled):
        messages.append(msg)
        return {"sent": True}
    poll_crypto_alerts(Broker([sol("102")]), {"SOLUSD": {"highest_since_entry": "110"}},
                       str(tmp_path / "alerts.db"), sender=sender)
    assert any("PROFIT EXIT SIGNAL" in message for message in messages)


def test_failed_delivery_does_not_acknowledge(tmp_path):
    messages = []
    def sender(message, *, enabled):
        messages.append(message)
        return {"sent": len(messages) >= 2}
    path = str(tmp_path / "alerts.db")
    poll_crypto_alerts(Broker([sol()]), {}, path, sender=sender)
    poll_crypto_alerts(Broker([sol()]), {}, path, sender=sender)
    assert len(messages) == 2


def test_confirmed_sell_only_after_monitor_activation(tmp_path):
    path = str(tmp_path / "alerts.db")
    messages = []
    def sender(msg, *, enabled):
        messages.append(msg)
        return {"sent": True}
    t = datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)
    poll_crypto_alerts(Broker(), {}, path, sender=sender, now=t)
    order = N(id="filled-order", symbol="SOLUSD", status="filled", side="sell",
              filled_at=datetime(2026, 10, 25, 10, 1, tzinfo=timezone.utc),
              filled_qty="2", filled_avg_price="110")
    broker = Broker(orders=[order])
    poll_crypto_alerts(broker, {}, path, sender=sender,
                       now=datetime(2026, 10, 25, 10, 5, tzinfo=timezone.utc))
    poll_crypto_alerts(broker, {}, path, sender=sender,
                       now=datetime(2026, 10, 25, 10, 20, tzinfo=timezone.utc))
    assert len(messages) == 1
    assert "CONFIRMED CRYPTO SELL" in messages[0]


def test_status_is_read_only_and_tracks_success(tmp_path):
    from backend.v19_crypto_telegram_monitor import crypto_monitor_status
    path = str(tmp_path / "status.db")
    before = crypto_monitor_status(path)
    assert before["lastSuccessfulPollAt"] is None
    poll_crypto_alerts(Broker([sol("95")]), {}, path, sender=lambda *_args, **_kw: {"sent": True})
    after = crypto_monitor_status(path)
    assert after["lastSuccessfulPollAt"] is not None
    assert after["nextExpectedPollAt"] is not None
    assert after["lastPositionCount"] == 1
    assert after["lastAlertSentAt"] is None


def test_status_tracks_delivery_failure_and_retry(tmp_path):
    from backend.v19_crypto_telegram_monitor import crypto_monitor_status
    path = str(tmp_path / "status.db")
    poll_crypto_alerts(Broker([sol("103")]), {}, path,
                       sender=lambda *_args, **_kwargs: {"sent": False})
    observed = crypto_monitor_status(path)
    assert observed["lastDeliveryFailureAt"] is not None
    assert observed["lastAlertSentAt"] is None
