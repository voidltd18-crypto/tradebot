"""All mocked: no real paper account or market-data request is made."""
import io
import json
from datetime import datetime, timezone
import pytest

from scripts.verify_fmc_paper_history_readonly import check_paper_and_history


class Response(io.BytesIO):
    def __init__(self, value):
        super().__init__(json.dumps(value).encode())


def test_verification_uses_get_only_paper_then_history():
    calls = []
    def paper_open(request, timeout):
        assert request.get_method() == "GET"
        assert request.full_url == "https://paper-api.alpaca.markets/v2/account"
        calls.append("paper")
        return Response({"id": "mock-paper", "status": "ACTIVE"})
    def bars_open(request, timeout):
        assert calls == ["paper"]
        assert request.get_method() == "GET"
        assert request.full_url.startswith(
            "https://data.alpaca.markets/v2/stocks/FMC/bars?"
        )
        calls.append("history")
        base = datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc)
        from datetime import timedelta
        prices = [5.48, 5.50, 5.52, 5.57, 5.63, 5.59, 5.55, 5.51]
        return Response({"bars": [
            {"t": (base + timedelta(minutes=i)).isoformat(), "c": p}
            for i, p in enumerate(prices)
        ], "next_page_token": None})
    result = check_paper_and_history(
        start="2026-11-09T14:30:00Z", end="2026-11-09T16:00:00Z",
        entry_price=5.485,
        environ={"PAPER_ALPACA_API_KEY": "fake", "PAPER_ALPACA_SECRET_KEY": "fake"},
        paper_opener=paper_open, history_opener=bars_open,
    )
    assert calls == ["paper", "history"]
    assert result["paperEndpointVerified"]
    assert result["dataCount"] == 8
    assert not result["paperOrderSubmitted"]
    assert not result["liveOrderSubmitted"]
    assert not result["releaseReady"]


def test_no_creds_fails_before_network():
    with pytest.raises(ValueError, match="PAPER"):
        check_paper_and_history(
            start="2026-11-09T14:30:00Z", end="2026-11-09T16:00:00Z",
            entry_price=5.485, environ={},
            paper_opener=lambda *a, **k: pytest.fail("must not call network"),
        )


def test_paper_account_failure_prevents_market_data_request():
    def bad_paper(request, timeout):
        return Response({"not_account": True})
    with pytest.raises(ValueError, match="invalid paper account"):
        check_paper_and_history(
            start="2026-11-09T14:30:00Z", end="2026-11-09T16:00:00Z",
            entry_price=5.485,
            environ={"PAPER_ALPACA_API_KEY": "fake", "PAPER_ALPACA_SECRET_KEY": "fake"},
            paper_opener=bad_paper,
            history_opener=lambda *a, **k: pytest.fail("market call prohibited"),
        )
