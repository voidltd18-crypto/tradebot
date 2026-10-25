from decimal import Decimal
from types import SimpleNamespace
from backend.v19_reports_crypto_rebuy import available_crypto_cash, crypto_rebuy_preview, parse_request


class FakeClient:
    def __init__(self, **kwargs):
        self.account = SimpleNamespace(**kwargs)
    def get_account(self):
        return self.account


def test_available_uses_lesser_of_cash_and_nonmarginable_buying_power():
    assert str(available_crypto_cash(FakeClient(cash="173.456", non_marginable_buying_power="200").get_account())) == "173.45"
    assert str(available_crypto_cash(FakeClient(cash="500", non_marginable_buying_power="80.04").get_account())) == "80.04"


def test_missing_unusable_or_negative_cash_is_not_spendable():
    for fields in (dict(cash="500"), dict(cash="nan", non_marginable_buying_power="800"),
                   dict(cash="-12", non_marginable_buying_power="80"), dict(cash="0", non_marginable_buying_power="1000")):
        assert available_crypto_cash(FakeClient(**fields).get_account()) == 0


def test_preview_is_read_only():
    preview = crypto_rebuy_preview(FakeClient(cash="75.79", non_marginable_buying_power="75.79"))
    assert preview["availableUsd"] == "75.79"
    assert preview["canBuy"] is True


def test_preview_fails_closed_on_api_outage():
    class Broken:
        def get_account(self):
            raise ConnectionError("unavailable")
    assert crypto_rebuy_preview(Broken())["canBuy"] is False


def test_amount_can_exceed_previous_250_cap_but_must_be_cash_backed_at_execution():
    assert parse_request("BTC/USD", "910.53", "BUY BTC/USD")[1] == Decimal("910.53")
