"""No broker access. Journal survives a recreated client on same disk."""
import pytest
from backend.stock_sell_recovery_journal import SellRecoveryJournal


def test_reserve_before_send_deduplicates_restart(tmp_path):
    path = tmp_path / "sell.db"
    first = SellRecoveryJournal(path)
    assert first.reserve_before_submit("FMC", "lot-1", "attempt-1", 10)
    restarted = SellRecoveryJournal(path)
    assert not restarted.reserve_before_submit("FMC", "lot-1", "attempt-2", 10)
    assert not restarted.reserve_before_submit("FMC", "lot-2", "attempt-1", 10)
    assert restarted.snapshot("FMC", "lot-1")["status"] == "RESERVED"


def test_ambiguous_submit_remains_blocked_after_restart(tmp_path):
    path = tmp_path / "sell.db"
    journal = SellRecoveryJournal(path)
    journal.reserve_before_submit("FMC", "lot-1", "attempt-1", 8)
    assert journal.mark_unknown("FMC", "lot-1")
    after_crash = SellRecoveryJournal(path)
    assert after_crash.snapshot("FMC", "lot-1")["status"] == "UNKNOWN"
    assert not after_crash.reserve_before_submit("FMC", "lot-1", "retry", 8)
    after_crash.broker_ack("FMC", "lot-1", "attempt-1", "order-1")
    assert after_crash.snapshot("FMC", "lot-1")["status"] == "ACKNOWLEDGED"


def test_partial_fill_then_cancellation_requires_fresh_position(tmp_path):
    journal = SellRecoveryJournal(tmp_path / "sell.db")
    journal.reserve_before_submit("FMC", "lot-1", "attempt-1", 10)
    journal.broker_ack("FMC", "lot-1", "attempt-1", "order-1")
    result = journal.reconcile(
        "FMC", "lot-1", broker_order_id="order-1",
        order_status="partially_filled", filled_qty=4, fresh_position_qty=6)
    assert result["status"] == "PARTIAL"
    result = journal.reconcile(
        "FMC", "lot-1", broker_order_id="order-1",
        order_status="canceled", filled_qty=4, fresh_position_qty=6)
    assert result["status"] == "TERMINAL_AWAIT_POSITION"
    assert not journal.reserve_before_submit("FMC", "lot-1", "new", 6)


def test_filled_and_flat_still_blocks_reuse_of_same_lot(tmp_path):
    journal = SellRecoveryJournal(tmp_path / "sell.db")
    journal.reserve_before_submit("FMC", "lot-1", "attempt-1", 10)
    journal.broker_ack("FMC", "lot-1", "attempt-1", "order-1")
    result = journal.reconcile(
        "FMC", "lot-1", broker_order_id="order-1",
        order_status="filled", filled_qty=10, fresh_position_qty=0)
    assert result["status"] == "VERIFIED_FLAT"
    assert not SellRecoveryJournal(tmp_path / "sell.db").reserve_before_submit(
        "FMC", "lot-1", "repeat", 10)


def test_broker_identity_mismatch_fails_closed(tmp_path):
    journal = SellRecoveryJournal(tmp_path / "sell.db")
    journal.reserve_before_submit("FMC", "lot-1", "attempt-1", 10)
    journal.broker_ack("FMC", "lot-1", "attempt-1", "order-1")
    with pytest.raises(ValueError, match="identity"):
        journal.reconcile(
            "FMC", "lot-1", broker_order_id="another",
            order_status="filled", filled_qty=10, fresh_position_qty=0)
    assert journal.snapshot("FMC", "lot-1")["blockedFromResubmit"]


def test_inconsistent_broker_fill_never_unlocks(tmp_path):
    journal = SellRecoveryJournal(tmp_path / "sell.db")
    journal.reserve_before_submit("FMC", "lot-1", "attempt-1", 10)
    journal.broker_ack("FMC", "lot-1", "attempt-1", "order-1")
    journal.reconcile(
        "FMC", "lot-1", broker_order_id="order-1",
        order_status="partially_filled", filled_qty=4, fresh_position_qty=6)
    with pytest.raises(ValueError, match="inconsistent"):
        journal.reconcile(
            "FMC", "lot-1", broker_order_id="order-1",
            order_status="partially_filled", filled_qty=2, fresh_position_qty=8)
    assert journal.snapshot("FMC", "lot-1")["status"] == "PARTIAL"


def test_missing_order_fails_closed_and_no_ephemeral_memory(tmp_path):
    with pytest.raises(ValueError):
        SellRecoveryJournal(":memory:")
    journal = SellRecoveryJournal(tmp_path / "sell.db")
    assert not journal.snapshot("FMC", "unknown")["blockedFromResubmit"]
    with pytest.raises(ValueError):
        journal.broker_ack("FMC", "unknown", "attempt-1", "order-1")
