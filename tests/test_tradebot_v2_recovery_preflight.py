"""Fail-closed, read-only durable recovery preflight."""
from decimal import Decimal
from backend.tradebot_v2.durable_reservations import Reservation
from backend.tradebot_v2.recovery_preflight import check_restart_preflight


def reservation(status="submitted_unknown"):
    return Reservation("req-1", "offline-1", "AAPL", "BUY", Decimal(1), status)


def test_empty_durable_store_allows_only_preflight():
    result = check_restart_preflight("isolated-test", reader=lambda _: [])
    assert result.allowed and result.active_count == 0


def test_unknown_submission_blocks_restart():
    result = check_restart_preflight("isolated-test", reader=lambda _: [reservation()])
    assert not result.allowed and result.active_count == 1


def test_reserved_order_blocks_restart():
    assert not check_restart_preflight(
        "isolated-test", reader=lambda _: [reservation("reserved")]
    ).allowed


def test_partial_fill_blocks_restart():
    assert not check_restart_preflight(
        "isolated-test", reader=lambda _: [reservation("partially_filled")]
    ).allowed


def test_database_outage_fails_closed():
    def broken(_):
        raise ConnectionError("secret connection string")
    result = check_restart_preflight("isolated-test", reader=broken)
    assert not result.allowed
    assert "secret" not in result.reason


def test_missing_database_fails_closed():
    assert not check_restart_preflight("", reader=lambda _: []).allowed


def test_invalid_recovery_payload_fails_closed():
    assert not check_restart_preflight("isolated-test", reader=lambda _: None).allowed


def test_invalid_reservation_status_fails_closed():
    assert not check_restart_preflight(
        "isolated-test", reader=lambda _: [reservation("filled")]
    ).allowed
