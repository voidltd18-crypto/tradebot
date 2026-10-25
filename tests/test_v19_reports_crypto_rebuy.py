from backend.v19_reports_crypto_rebuy import parse_request, rebuy_order
import pytest


def test_confirmation_and_limits():
    assert parse_request("XRP/USD", "25.00", "BUY XRP/USD")[0] == "XRP/USD"
    for args in [("XRP/USD", 0, "BUY XRP/USD"),
                 ("XRP/USD", 1000, "BUY XRP/USD"),
                 ("XRP/USD", "nan", "BUY XRP/USD"),
                 ("XRP/USD", 25, "BUY BTC/USD"),
                 ("MARA", 25, "BUY MARA"),
                 ("XRP/USD", "2.345", "BUY XRP/USD")]:
        with pytest.raises(ValueError):
            parse_request(*args)


class NoBrokerCalls:
    def __getattr__(self, name):
        raise AssertionError("broker should never be contacted")


def test_disabled_feature_never_accesses_broker():
    result = rebuy_order(NoBrokerCalls(), symbol="XRP/USD", amount="25",
                         confirmation="BUY XRP/USD", allowed_ids={"XRP/USD"}, enabled=False)
    assert result["orderSubmitted"] is False


def test_missing_history_never_accesses_broker():
    result = rebuy_order(NoBrokerCalls(), symbol="XRP/USD", amount="25",
                         confirmation="BUY XRP/USD", allowed_ids=set(), enabled=True)
    assert result["orderSubmitted"] is False
