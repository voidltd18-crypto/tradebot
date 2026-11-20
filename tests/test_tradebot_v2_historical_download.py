import io
import json
from urllib.parse import parse_qs, urlparse

import pytest

from backend.tradebot_v2.historical_download import download_daily_bars


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def opener(pages, requests):
    def open_request(req, timeout):
        requests.append(req)
        return Response(json.dumps(pages.pop(0)).encode())
    return open_request


def bar(day, price):
    return {"t": f"2025-01-{day:02d}T00:00:00Z", "c": price}


def test_paginates_and_requests_adjusted_daily_bars():
    requests = []
    pages = [
        {"bars": {"AAPL": [bar(1, 100)]}, "next_page_token": "next"},
        {"bars": {"AAPL": [bar(2, 101)]}, "next_page_token": None},
    ]
    result = download_daily_bars("AAPL", "2025-01-01", "2025-02-01",
                                 api_key="test", api_secret="test",
                                 opener=opener(pages, requests))
    assert len(result) == 2
    assert len(requests) == 2
    params = parse_qs(urlparse(requests[0].full_url).query)
    assert params["adjustment"] == ["all"]
    assert params["timeframe"] == ["1Day"]
    assert params["feed"] == ["iex"]
    assert parse_qs(urlparse(requests[1].full_url).query)["page_token"] == ["next"]


def test_incomplete_pages_fail_closed():
    with pytest.raises(ValueError, match="incomplete"):
        download_daily_bars(
            "AAPL", "2025-01-01", "2025-02-01", api_key="test",
            api_secret="test", max_pages=1,
            opener=opener([{"bars": {"AAPL": [bar(1, 100)]},
                            "next_page_token": "more"}], []),
        )


def test_repeated_page_token_fails_closed():
    pages = [{"bars": {"AAPL": [bar(1, 100)]}, "next_page_token": "same"},
             {"bars": {"AAPL": [bar(2, 101)]}, "next_page_token": "same"}]
    with pytest.raises(ValueError, match="repeated"):
        download_daily_bars(
            "AAPL", "2025-01-01", "2025-02-01", api_key="test",
            api_secret="test", opener=opener(pages, []),
        )


@pytest.mark.parametrize("symbol", ["TSLA", "BTC/USD", ""])
def test_unapproved_symbols_cannot_be_downloaded(symbol):
    with pytest.raises(ValueError):
        download_daily_bars(symbol, "2025-01-01", "2025-02-01")


def test_credentials_required(monkeypatch):
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    with pytest.raises(ValueError, match="credentials"):
        download_daily_bars("AAPL", "2025-01-01", "2025-02-01")
