from datetime import datetime, timezone, timedelta
from backend.tradebot_v2.ledger import OwnershipEvent, reconcile

T = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)

def event(i, symbol, kind, quantity):
    return OwnershipEvent(str(i), symbol, "broker-order-" + str(i), kind, quantity, T)

def test_existing_holdings_never_assigned():
    result = reconcile([], {"MSFT": 2, "NVDA": 3})
    assert not result.verified and result.managed == {}

def test_missing_ledger_fails_closed():
    assert not reconcile(None, {"NVDA": 1}).verified

def test_verified_fill_reconciles():
    result = reconcile([event(1, "AAPL", "BUY_FILLED", 2)], {"AAPL": 2})
    assert result.verified and result.managed == {"AAPL": 2}

def test_broker_mismatch_blocks():
    assert not reconcile([event(1, "AAPL", "BUY_FILLED", 2)], {"AAPL": 1}).verified

def test_sale_cannot_exceed_owned_shares():
    assert not reconcile([event(1, "AAPL", "SELL_FILLED", 1)], {"AAPL": 0}).verified

def test_duplicate_event_blocks():
    e = event(1, "AAPL", "BUY_FILLED", 1)
    assert not reconcile([e, e], {"AAPL": 2}).verified

def test_partial_sale_updates_quantity():
    result = reconcile([event(1, "AAPL", "BUY_FILLED", 2), event(2, "AAPL", "SELL_FILLED", 1)], {"AAPL": 1})
    assert result.verified and result.managed["AAPL"] == 1


def test_non_finite_fill_quantity_fails_closed():
    for bad in (float("nan"), float("inf"), float("-inf")):
        assert not reconcile([event(1, "AAPL", "BUY_FILLED", bad)], {"AAPL": 10}).verified


def test_non_finite_broker_quantity_fails_closed():
    for bad in (float("nan"), float("inf"), float("-inf")):
        assert not reconcile([event(1, "AAPL", "BUY_FILLED", 1)], {"AAPL": bad}).verified
