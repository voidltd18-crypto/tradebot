"""Offline integrated smoke regression: no real broker interaction."""
from backend.tradebot_v2.offline_smoke import run_smoke


def test_integrated_smoke_cycle():
    result = run_smoke()
    assert result["result"] == "PASS"
    assert result["broker_orders"] == 0
    assert result["execution_enabled"] is False
    assert result["synthetic_buy"] == "GREEN"
    assert result["duplicate_order"] == "RED"
    assert result["manual_share_sale"] == "RED"
    assert result["synthetic_sell"] == "GREEN"
    assert result["shutdown_buy"] == "RED"
