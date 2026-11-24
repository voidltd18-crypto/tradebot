from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from backend.tradebot_v2.broker_recovery import SubmissionIntent, read_broker_observation


@pytest.fixture
def recovery_case():
    intent = SubmissionIntent(uuid4(), "recorded-buy", "AAPL", "buy", Decimal("2"))
    reader = Mock()
    reader.get_account.return_value = SimpleNamespace(id=intent.account_id)
    reader.get_order_by_client_id.return_value = SimpleNamespace(
        id=uuid4(), client_order_id=intent.client_order_id, symbol="AAPL",
        side="buy", status="partially_filled", qty="2", filled_qty="0.5",
    )
    return reader, intent


def test_reads_partial_fill_using_the_durable_client_id(recovery_case):
    reader, intent = recovery_case
    result = read_broker_observation(reader, intent)
    reader.get_order_by_client_id.assert_called_once_with(intent.client_order_id)
    assert result.broker_order_id == reader.get_order_by_client_id.return_value.id
    assert result.status == "partially_filled"
    assert result.cumulative_filled == Decimal("0.5")


@pytest.mark.parametrize("failure", [TimeoutError, LookupError])
def test_failed_lookup_leaves_outcome_unresolved(recovery_case, failure):
    reader, intent = recovery_case
    reader.get_order_by_client_id.side_effect = failure
    assert read_broker_observation(reader, intent) is None


@pytest.mark.parametrize("field,value", [
    ("symbol", "MSFT"), ("side", "sell"), ("qty", "3"), ("filled_qty", "NaN"),
    ("status", "replaced"), ("status", "pending_cancel"), ("status", "filled"),
    ("client_order_id", "another-order"),
])
def test_untrustworthy_order_evidence_is_ignored(recovery_case, field, value):
    reader, intent = recovery_case
    setattr(reader.get_order_by_client_id.return_value, field, value)
    assert read_broker_observation(reader, intent) is None


def test_wrong_account_and_offline_ids_never_reach_order_lookup(recovery_case):
    reader, intent = recovery_case
    assert read_broker_observation(reader, replace(intent, account_id=uuid4())) is None
    assert read_broker_observation(reader, replace(intent, client_order_id="offline-123")) is None
    reader.get_order_by_client_id.assert_not_called()


def test_fill_regression_or_broker_order_id_change_keeps_reservation_unresolved(recovery_case):
    reader, intent = recovery_case
    assert read_broker_observation(reader, replace(intent, cumulative_filled=Decimal(1))) is None
    assert read_broker_observation(reader, replace(intent, broker_order_id=uuid4())) is None


def test_cancelled_order_preserves_partial_fill_evidence(recovery_case):
    reader, intent = recovery_case
    reader.get_order_by_client_id.return_value.status = "canceled"
    result = read_broker_observation(reader, intent)
    assert result.status == "cancelled"
    assert result.cumulative_filled == Decimal("0.5")
