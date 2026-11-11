import io
import json

import pytest

from backend.stock_paper_account_reader import PaperAccountReader, PAPER_BASE


class FakeResponse(io.BytesIO):
    def __init__(self, data):
        super().__init__(json.dumps(data).encode("utf-8"))


def test_get_only_paper_account_position_and_order_reads():
    visited = []
    results = {
        "/v2/account": {"id": "paper-1", "status": "ACTIVE"},
        "/v2/positions/FMC": {"symbol": "FMC", "qty": "5", "avg_entry_price": "5.485"},
        "/v2/orders": [{"id": "order-1", "symbol": "FMC", "side": "sell",
                         "status": "partially_filled", "filled_qty": "2"}],
    }
    def fake_open(request, timeout):
        assert timeout == 15
        assert request.get_method() == "GET"
        assert request.full_url.startswith(PAPER_BASE + "/v2/")
        visited.append(request.full_url)
        return FakeResponse(results[request.full_url.removeprefix(PAPER_BASE)])
    client = PaperAccountReader(api_key="paper-test", api_secret="paper-test",
                                opener=fake_open)
    assert client.confirm_paper_account()["paperOnly"]
    assert client.position()["qty"] == "5"
    assert client.orders()[0]["status"] == "partially_filled"
    assert len(visited) == 3


@pytest.mark.parametrize("bad_url", [
    "https://api.alpaca.markets", "http://paper-api.alpaca.markets",
    "https://paper-api.alpaca.markets.evil.com",
])
def test_live_or_untrusted_endpoint_refused(bad_url):
    with pytest.raises(ValueError):
        PaperAccountReader(api_key="test", api_secret="test", base_url=bad_url)


def test_paper_credentials_required():
    with pytest.raises(ValueError):
        PaperAccountReader(api_key="", api_secret="")


def test_symbols_restricted_to_fmc():
    reader = PaperAccountReader(api_key="test", api_secret="test",
                                opener=lambda *a, **k: None)
    with pytest.raises(ValueError):
        reader.position("MARA")


def test_no_order_submission_method():
    client = PaperAccountReader(api_key="test", api_secret="test")
    assert not hasattr(client, "submit_order")
    assert not hasattr(client, "cancel_order")
