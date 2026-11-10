import pytest
from backend.stock_exit_state_store import ExitState


def test_peak_survives_restart_and_never_moves_down(tmp_path):
    path = tmp_path / "shadow.sqlite"
    store = ExitState(path)
    assert store.observe("FMC", "alpaca-entry-1", 5.5) == 5.5
    assert store.observe("FMC", "alpaca-entry-1", 5.4) == 5.5
    recovered = ExitState(path)
    assert recovered.snapshot("FMC", "alpaca-entry-1")["peakPrice"] == 5.5
    assert recovered.observe("FMC", "alpaca-entry-1", 5.7) == 5.7
    assert not recovered.snapshot("FMC", "alpaca-entry-2")["found"]


def test_reservation_survives_restart_and_blocks_duplicate(tmp_path):
    path = tmp_path / "shadow.sqlite"
    first = ExitState(path)
    assert not first.reserve_once("FMC", "lot-1", "signal-1")  # position unknown
    first.observe("FMC", "lot-1", 5.6)
    assert first.reserve_once("FMC", "lot-1", "signal-1")
    recovered = ExitState(path)
    assert not recovered.reserve_once("FMC", "lot-1", "signal-2")
    snapshot = recovered.snapshot("FMC", "lot-1")
    assert snapshot["reserved"] is True
    assert snapshot["reservationId"] == "signal-1"


def test_only_verified_flat_can_clear_state(tmp_path):
    store = ExitState(tmp_path / "shadow.sqlite")
    store.observe("FMC", "lot-1", 5.6)
    store.reserve_once("FMC", "lot-1", "signal-1")
    with pytest.raises(ValueError):
        store.clear_after_verified_flat("FMC", "lot-1", verified_flat=False)
    assert store.snapshot("FMC", "lot-1")["reserved"]
    assert store.clear_after_verified_flat("FMC", "lot-1", verified_flat=True)
    assert not store.snapshot("FMC", "lot-1")["found"]


def test_invalid_inputs_fail_closed(tmp_path):
    store = ExitState(tmp_path / "shadow.sqlite")
    with pytest.raises(ValueError):
        store.observe("FMC", "lot", float("nan"))
    with pytest.raises(ValueError):
        store.observe("FMC", "", 5.5)
    with pytest.raises(ValueError):
        store.reserve_once("FMC", "lot", "")
    with pytest.raises(ValueError):
        ExitState(":memory:")
