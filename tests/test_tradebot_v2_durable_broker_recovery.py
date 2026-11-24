"""Read-only Alpaca SDK fixtures backed by disposable PostgreSQL."""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event
from uuid import UUID, uuid4

import pytest

from backend.tradebot_v2.broker_recovery import SubmissionIntent
from backend.tradebot_v2.durable_broker_recovery import (
    record_submission_intent,
    recover_broker_intents,
)
from backend.tradebot_v2.durable_reservations import reserve_offline, update_offline
from backend.tradebot_v2.execution_plan import plan_sell
from backend.tradebot_v2.ledger import OwnershipEvent
from backend.tradebot_v2.recovery_gated_simulation import simulate_sell_after_recovery
from backend.tradebot_v2.recovery_preflight import check_restart_preflight
from backend.tradebot_v2.store import read_verified_ownership

ACCOUNT = UUID("8e68de51-1dc8-4c01-ad8d-d0fa4fdfd66e")
ORDER = str(UUID("d497cb27-1186-4917-b7cf-fdf9632d4ffa"))
INTENT = SubmissionIntent(ACCOUNT, "recorded-order", "AAPL", "buy", Decimal(2))
POSITIONS = {"MSFT": 1.0, "NVDA": 2.0, "AAPL": 0.5}
NOW = datetime(2025, 1, 2, 15, tzinfo=timezone.utc)


@pytest.fixture
def database():
    url = os.getenv("TRADEBOT_V2_RECOVERY_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires disposable PostgreSQL")
    import psycopg
    from psycopg.conninfo import make_conninfo

    schema = "recovery_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
        database_url = make_conninfo(url, options=f"-c search_path={schema}")
        try:
            with psycopg.connect(database_url) as isolated:
                for migration in sorted(Path("backend/tradebot_v2/migrations").glob("*.sql")):
                    isolated.execute(migration.read_text())
            yield database_url
        finally:
            conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


def broker_payload(status="partially_filled", cumulative="0.5", *, revision=5):
    created = NOW.isoformat()
    updated = (NOW + timedelta(seconds=revision)).isoformat()
    return {
        "account": {"id": str(ACCOUNT), "account_number": "fixture", "status": "ACTIVE"},
        "order": {
            "id": ORDER, "client_order_id": INTENT.client_order_id, "symbol": INTENT.symbol,
            "qty": "2", "filled_qty": cumulative, "status": status, "side": "buy",
            "order_class": "", "time_in_force": "day", "extended_hours": False,
            "created_at": created, "updated_at": updated, "submitted_at": created,
        },
        "fills": [
            {
                "id": "fill-" + str(index), "order_id": ORDER, "activity_type": "FILL",
                "symbol": INTENT.symbol, "side": "buy", "type": "partial_fill",
                "transaction_time": (NOW + timedelta(seconds=1)).isoformat(),
                "qty": "0.25", "cum_qty": total,
            }
            for index, total in enumerate(("0.25", "0.5"))
        ],
    }


def fixture_reader(payload, *, lookup_error=None, synchronize=None, pages=None):
    from alpaca.trading.client import TradingClient

    class FixtureClient(TradingClient):
        def _request(self, method, path, data=None, **kwargs):
            assert method == "GET"
            if path == "/account":
                return payload["account"]
            if path == "/orders:by_client_order_id":
                assert data == {"client_order_id": INTENT.client_order_id}
                if lookup_error:
                    raise lookup_error
                if synchronize:
                    synchronize()
                return payload["order"]
            assert path == "/account/activities/FILL"
            assert data["direction"] == "asc"
            return payload["fills"] if pages is None else pages[data.get("page_token")]

    return FixtureClient("fixture-key", "fixture-secret")


def state(database):
    import psycopg

    with psycopg.connect(database) as conn:
        order = conn.execute("""
            SELECT status, cumulative_filled FROM tradebot_v2_order_reservations
            WHERE request_id = 'request'
        """).fetchone()
        events = conn.execute("""
            SELECT quantity FROM tradebot_v2_fill_events ORDER BY event_id
        """).fetchall()
    return order, [row[0] for row in events]


def test_fresh_process_recovers_partial_fill_after_interruption_and_then_cancellation(database, tmp_path):
    broker_state = tmp_path / "broker.json"
    child_env = dict(os.environ, RECOVERY_FIXTURE_DATABASE=database,
                     RECOVERY_BROKER_STATE=str(broker_state),
                     PYTHONPATH=os.pathsep.join((".", "tests")))
    # The process persists the intent, simulates the broker accepting it and
    # exits before it can persist the order acknowledgement.
    crashed = subprocess.run([sys.executable, "-c", """
import json, os
from pathlib import Path
from test_tradebot_v2_durable_broker_recovery import INTENT, broker_payload, record_submission_intent
record_submission_intent(os.environ["RECOVERY_FIXTURE_DATABASE"], "request", INTENT)
payload = broker_payload()
payload["fills"].append(payload["fills"][0].copy())
Path(os.environ["RECOVERY_BROKER_STATE"]).write_text(json.dumps(payload))
os._exit(17)
"""], env=child_env, timeout=20)
    assert crashed.returncode == 17
    assert state(database) == (("submitted_unknown", 0), [])
    assert not check_restart_preflight(database).allowed
    with pytest.raises(RuntimeError, match="Outstanding"):
        reserve_offline(database, "new", "AMZN", "buy", 1)

    recovered = subprocess.run([sys.executable, "-c", """
import json, os
from dataclasses import asdict
from pathlib import Path
from test_tradebot_v2_durable_broker_recovery import check_restart_preflight, fixture_reader
payload = json.loads(Path(os.environ["RECOVERY_BROKER_STATE"]).read_text())
print(json.dumps(asdict(check_restart_preflight(
    os.environ["RECOVERY_FIXTURE_DATABASE"], broker_reader=fixture_reader(payload)
))))
"""], env=child_env, capture_output=True, text=True, check=True, timeout=20)
    preflight = json.loads(recovered.stdout)
    assert not preflight["allowed"] and preflight["active_count"] == 1
    assert state(database) == (("partially_filled", Decimal("0.5")), [Decimal("0.25")] * 2)
    assert not check_restart_preflight(database).allowed

    reader = fixture_reader(broker_payload("canceled", revision=7))
    assert check_restart_preflight(database, broker_reader=reader).allowed
    assert recover_broker_intents(database, reader) == []
    assert state(database) == (("cancelled", Decimal("0.5")), [Decimal("0.25")] * 2)
    assert check_restart_preflight(database).allowed

    ownership = read_verified_ownership(database, POSITIONS, account_id=ACCOUNT)
    assert ownership.verified and ownership.managed == {"AAPL": 0.5}
    assert not read_verified_ownership(database, POSITIONS, account_id=uuid4()).verified
    for symbol in ("MSFT", "NVDA"):
        assert not plan_sell(symbol, 1, 0, POSITIONS[symbol]).permitted
    plan = plan_sell("AAPL", "0.5", "0.5", "0.5", verified_bot_origin=True,
                     ledger_reconciled=True, market_data_verified=True)
    assert not plan.permitted and "ambiguous ownership" in plan.reason
    result = simulate_sell_after_recovery(
        database_url=database, symbol="AAPL", quantity=0.5, broker_positions=POSITIONS,
        verified_fill_events=[OwnershipEvent("fill", "AAPL", ORDER, "BUY_FILLED", 0.5, NOW)],
        request_id="sell",
    )
    assert result.status == "RED" and "ownership" in result.reason.lower()


@pytest.mark.parametrize("problem", ["missing", "timeout", "account", "incomplete", "conflict"])
def test_unverified_observation_keeps_intent_active(database, problem):
    record_submission_intent(database, "request", INTENT)
    payload = broker_payload()
    error = None
    if problem == "missing":
        error = LookupError()
    elif problem == "timeout":
        error = TimeoutError()
    elif problem == "account":
        payload["account"]["id"] = str(uuid4())
    elif problem == "incomplete":
        payload["fills"].pop()
    elif problem == "conflict":
        payload["fills"].append(dict(payload["fills"][0], qty="0.1"))
    assert recover_broker_intents(database, fixture_reader(payload, lookup_error=error)) == []
    assert state(database) == (("submitted_unknown", 0), [])
    assert not check_restart_preflight(database).allowed


def test_simulated_reservations_never_create_ownership(database):
    reserve_offline(database, "sim", "MSFT", "buy", 1)
    update_offline(database, "sim", "accepted", 0)
    update_offline(database, "sim", "filled", 1)
    assert recover_broker_intents(database, object()) == []
    ownership = read_verified_ownership(database, POSITIONS, account_id=ACCOUNT)
    assert not ownership.verified and ownership.managed == {}


def test_concurrent_stale_partial_snapshot_cannot_overwrite_cancellation(database):
    record_submission_intent(database, "request", INTENT)
    barrier = Barrier(2)
    cancelled = Event()

    def wait_for_cancel():
        barrier.wait(timeout=10)
        assert cancelled.wait(timeout=10)

    with ThreadPoolExecutor(2) as pool:
        partial = pool.submit(recover_broker_intents, database,
                              fixture_reader(broker_payload(), synchronize=wait_for_cancel))
        try:
            reader = fixture_reader(broker_payload("canceled", revision=8), synchronize=barrier.wait)
            assert recover_broker_intents(database, reader) == ["request"]
        finally:
            cancelled.set()
        assert partial.result(timeout=15) == []
    assert state(database) == (("cancelled", Decimal("0.5")), [Decimal("0.25")] * 2)


def test_decreasing_fill_and_stale_timestamp_cannot_change_active_state(database):
    record_submission_intent(database, "request", INTENT)
    reader = fixture_reader(broker_payload())
    assert recover_broker_intents(database, reader) == ["request"]
    for payload in (broker_payload("canceled", "0.25", revision=7),
                    broker_payload("canceled", revision=4)):
        assert recover_broker_intents(database, fixture_reader(payload)) == []
    assert state(database) == (("partially_filled", Decimal("0.5")), [Decimal("0.25")] * 2)


def test_database_failure_rolls_back_fills_and_lifecycle(database):
    import psycopg

    record_submission_intent(database, "request", INTENT)
    with psycopg.connect(database) as conn:
        conn.execute("""
            ALTER TABLE tradebot_v2_order_reservations ADD CONSTRAINT injected_failure
            CHECK (status = 'submitted_unknown')
        """)
    reader = fixture_reader(broker_payload())
    with pytest.raises(psycopg.errors.CheckViolation):
        recover_broker_intents(database, reader)
    assert state(database) == (("submitted_unknown", 0), [])
    assert not check_restart_preflight(database).allowed
    with psycopg.connect(database) as conn:
        conn.execute("ALTER TABLE tradebot_v2_order_reservations DROP CONSTRAINT injected_failure")
    assert recover_broker_intents(database, reader) == ["request"]
    assert state(database) == (("partially_filled", Decimal("0.5")), [Decimal("0.25")] * 2)


@pytest.mark.parametrize("tail", ["complete", "missing", "repeated", "wrong_account", "naive_time"])
def test_paginated_nine_decimal_activity(database, tail):
    intent = replace(INTENT, quantity=Decimal("0.123456789"))
    record_submission_intent(database, "request", intent)
    payload = broker_payload("filled", "0.123456789")
    payload["order"]["qty"] = "0.123456789"
    first, second = payload["fills"]
    first.update(qty="0.123456788", cum_qty="0.123456788")
    second.update(qty="0.000000001", cum_qty="0.123456789", type="fill")
    unrelated_id = str(uuid4())
    initial_page = [first, *[
        dict(first, order_id=unrelated_id, symbol="MSFT", id=f"unrelated-{index}")
        for index in range(99)
    ]]
    next_token = initial_page[-1]["id"]
    final_page = [second]
    if tail == "missing":
        final_page = []
    elif tail == "repeated":
        final_page = initial_page
    elif tail == "wrong_account":
        second["account_id"] = str(uuid4())
    elif tail == "naive_time":
        second["transaction_time"] = second["transaction_time"].removesuffix("+00:00")
    reader = fixture_reader(payload, pages={None: initial_page, next_token: final_page})
    if tail != "complete":
        assert recover_broker_intents(database, reader) == []
        assert state(database) == (("submitted_unknown", 0), [])
        assert not check_restart_preflight(database).allowed
        return
    assert recover_broker_intents(database, reader) == ["request"]
    assert state(database) == (
        ("filled", Decimal("0.123456789")),
        [Decimal("0.123456788"), Decimal("0.000000001")],
    )
    positions = {"AAPL": Decimal("0.123456789"), "MSFT": 1, "NVDA": 2}
    assert read_verified_ownership(database, positions, account_id=ACCOUNT).managed == {
        "AAPL": 0.123456789
    }
    positions["AAPL"] -= Decimal("0.000000001")
    assert not read_verified_ownership(database, positions, account_id=ACCOUNT).verified


def test_older_schema_cannot_silently_round_a_broker_fill(database):
    import psycopg

    record_submission_intent(database, "request", INTENT)
    with psycopg.connect(database) as conn:
        conn.execute("""
            ALTER TABLE tradebot_v2_order_reservations
            ALTER COLUMN cumulative_filled TYPE NUMERIC(24,8)
        """)
    payload = broker_payload(cumulative="0.250000001")
    payload["fills"][1].update(qty="0.000000001", cum_qty="0.250000001")
    with pytest.raises(RuntimeError, match="cannot store broker fill exactly"):
        recover_broker_intents(database, fixture_reader(payload))
    assert state(database) == (("submitted_unknown", 0), [])
