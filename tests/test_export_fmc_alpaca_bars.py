"""Stubbed market-data integration tests: no broker connection or orders."""
import io
import json
from datetime import datetime, timezone

import pytest

from scripts.export_fmc_alpaca_bars import export_fmc_bars, fetch_fmc_bars


START = "2026-11-09T14:30:00Z"
END = "2026-11-09T14:35:00Z"


class FakeResponse(io.BytesIO):
    def __init__(self, payload):
        super().__init__(json.dumps(payload).encode("utf-8"))


def test_paginated_fmc_export_is_get_only(tmp_path):
    requests = []
    pages = [
        {"bars": [{"t": "2026-11-09T14:30:00Z", "c": 5.45}], "next_page_token": "second"},
        {"bars": [{"t": "2026-11-09T14:31:00Z", "c": 5.46}], "next_page_token": None},
    ]
    def open_fake(req, timeout):
        assert req.get_method() == "GET"
        assert "data.alpaca.markets" in req.full_url
        assert "FMC/bars" in req.full_url
        assert "trading" not in req.full_url
        assert any(k.lower() == "apca-api-key-id" for k in req.headers)
        requests.append(req)
        return FakeResponse(pages[len(requests) - 1])
    path = tmp_path / "fmc.csv"
    result = export_fmc_bars(
        START, END, path, env={"APCA_API_KEY_ID": "test", "APCA_API_SECRET_KEY": "test"},
        opener=open_fake,
    )
    assert result["rows"] == 2
    assert result["tradesSubmitted"] == 0
    assert len(requests) == 2
    assert "5.46" in path.read_text()
    with pytest.raises(FileExistsError):
        export_fmc_bars(
            START, END, path,
            env={"APCA_API_KEY_ID": "test", "APCA_API_SECRET_KEY": "test"},
            opener=open_fake,
        )


def test_repeated_token_fails_closed():
    def open_fake(req, timeout):
        return FakeResponse({"bars": [], "next_page_token": "stuck"})
    with pytest.raises(ValueError, match="repeated"):
        fetch_fmc_bars(START, END, api_key="x", api_secret="y", opener=open_fake)


@pytest.mark.parametrize("start,end", [
    ("2026-11-09T14:35:00Z", "2026-11-09T14:30:00Z"),
    ("2026-01-01T00:00:00Z", "2026-11-09T14:30:00Z"),
    ("2026-11-09T14:30:00", "2026-11-09T14:35:00Z"),
    ("2026-11-09T14:30:00Z", "2099-01-01T00:00:00Z"),
])
def test_invalid_time_bounds_refused(start, end):
    with pytest.raises(ValueError):
        fetch_fmc_bars(start, end, api_key="x", api_secret="y", opener=lambda *_args, **_kwargs: None)


def test_reject_out_of_order_provider_data():
    def open_fake(req, timeout):
        return FakeResponse({"bars": [
            {"t": "2026-11-09T14:31:00Z", "c": 5.5},
            {"t": "2026-11-09T14:30:00Z", "c": 5.4},
        ]})
    with pytest.raises(ValueError, match="chronological"):
        fetch_fmc_bars(START, END, api_key="x", api_secret="y", opener=open_fake)


def test_missing_credentials_fail_before_network():
    with pytest.raises(ValueError, match="credentials"):
        fetch_fmc_bars(START, END, api_key="", api_secret="")
