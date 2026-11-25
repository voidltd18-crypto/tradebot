import importlib.util
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from alpaca.trading.client import TradingClient
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend import config, legacy
from backend.read_only_broker import ReadOnlyTradingClient


def test_stock_only_mode_blocks_crypto_scans_and_worker(monkeypatch):
    app = FastAPI()
    auth = Mock()
    fake_legacy = SimpleNamespace(
        app=app,
        verify_api_key=auth,
        ai_position_capacity_payload=lambda: {},
        trading_client=Mock(),
        state={},
        SQLITE_DB_FILE=":memory:",
    )
    monkeypatch.setitem(sys.modules, "backend.legacy.monolith", fake_legacy)
    monkeypatch.setattr(legacy, "monolith", fake_legacy, raising=False)
    monkeypatch.setattr(config, "CRYPTO_ENABLED", False)
    install_worker = Mock()
    monkeypatch.setattr(
        "backend.v19_crypto_telegram_monitor.install_crypto_telegram_worker", install_worker
    )

    spec = importlib.util.find_spec("backend.main")
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
    client = TestClient(app)

    for path in (
        "/v19/manual-crypto-rebuy-scan",
        "/v19/manual-crypto-rebuy-preview/BTCUSD",
        "/v19/xrp-repeat-cycle-preview",
    ):
        response = client.get(path)
        assert response.status_code == 403
        assert response.json()["detail"] == "Crypto monitoring is disabled."
    assert auth.call_count == 3
    assert client.post("/v19/reports/crypto-buy-again").json()["orderSubmitted"] is False
    install_worker.assert_not_called()
    assert fake_legacy.trading_client.mock_calls == []


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_monitoring_cannot_mutate_broker_state(monkeypatch, method):
    transport = Mock()
    monkeypatch.setattr(TradingClient, "_request", transport)
    broker = ReadOnlyTradingClient("fixture-key", "fixture-secret", paper=False)
    with pytest.raises(RuntimeError, match="read-only"):
        broker._request(method, "/orders")
    transport.assert_not_called()
    broker._request("GET", "/orders")
    transport.assert_called_once_with("GET", "/orders")
