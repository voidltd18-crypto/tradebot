from backend.tradebot_v2.durable_reservations import recover_active_offline
import pytest


def test_recovery_requires_isolated_database():
    with pytest.raises(ValueError):
        recover_active_offline("")


def test_reservation_states_are_explicit():
    from backend.tradebot_v2.durable_reservations import ACTIVE
    assert ACTIVE == {"reserved", "submitted_unknown", "accepted", "partially_filled"}
    assert "filled" not in ACTIVE
