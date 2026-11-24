"""Restart reconciliation for recorded intents. All broker calls are read-only."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from backend.tradebot_v2.broker_recovery import (
    AlpacaOrderReader,
    SubmissionIntent,
    read_broker_observation,
)
from backend.tradebot_v2.durable_reservations import (
    ACTIVE,
    lock_reservations,
    validate_reservation,
)
from backend.tradebot_v2.offline_orders import TRANSITIONS

BROKER_SHARE_INCREMENT = Decimal("0.000000001")

COLUMNS = """
    request_id, account_id, client_order_id, symbol, side, quantity,
    status, cumulative_filled, broker_order_id, broker_updated_at
"""


class AlpacaRecoveryReader(AlpacaOrderReader, Protocol):
    def get(self, path: str, data: dict): ...


def record_submission_intent(database_url: str, request_id: str, intent: SubmissionIntent):
    """Commit the submission identity before any external action can occur."""
    symbol, side, quantity = validate_reservation(
        database_url, request_id, intent.symbol, intent.side, intent.quantity,
        increment=BROKER_SHARE_INCREMENT,
    )
    client_id = intent.client_order_id
    if (not isinstance(intent.account_id, UUID) or not isinstance(client_id, str)
            or not client_id.strip() or client_id != client_id.strip()
            or len(client_id) > 48 or client_id.startswith(("offline-", "sim-"))
            or intent.cumulative_filled != 0 or intent.broker_order_id is not None):
        raise ValueError("Invalid initial broker intent")
    import psycopg

    identity = (request_id, intent.account_id, client_id, symbol, side, quantity)
    with psycopg.connect(database_url, connect_timeout=5) as conn, conn.cursor() as cur:
        lock_reservations(cur)
        cur.execute(f"""
            SELECT {COLUMNS} FROM tradebot_v2_order_reservations WHERE request_id = %s
        """, (request_id,))
        existing = cur.fetchone()
        if existing is not None:
            if existing[:6] != identity:
                raise ValueError("Idempotency key reused with different intent")
            return
        cur.execute("""
            SELECT 1 FROM tradebot_v2_order_reservations WHERE status = ANY(%s) LIMIT 1
        """, (list(ACTIVE),))
        if cur.fetchone():
            raise RuntimeError("Outstanding durable reservation")
        cur.execute("""
            INSERT INTO tradebot_v2_order_reservations
                (request_id, account_id, client_order_id, symbol, side, quantity, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'submitted_unknown')
            RETURNING quantity
        """, identity)
        if cur.fetchone()[0] != quantity:
            raise RuntimeError("Reservation schema cannot store broker quantity exactly")


def _timestamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if (not isinstance(value, datetime) or value.utcoffset() is None
            or value > datetime.now(timezone.utc)):
        raise ValueError("Invalid broker timestamp")
    return value


def _verified_fills(reader, intent, observation, created_at, updated_at):
    """Corroborate the full cumulative quantity using a chain of executions."""
    if not observation.cumulative_filled:
        return {}
    query = {
        "after": (created_at - timedelta(seconds=1)).isoformat(),
        "direction": "asc",
        "page_size": 100,
    }
    fills = {}
    tokens = set()
    # Treat incomplete, inconsistent or excessively large histories as unresolved.
    for _ in range(100):
        page = reader.get("/account/activities/FILL", data=query)
        if not isinstance(page, list) or len(page) > query["page_size"]:
            raise ValueError("Invalid fill activity page")
        for activity in page:
            if UUID(activity["order_id"]) != observation.broker_order_id:
                continue
            activity_id = activity["id"]
            account_id = activity.get("account_id")
            qty = Decimal(activity["qty"])
            cumulative = Decimal(activity["cum_qty"])
            when = _timestamp(activity["transaction_time"])
            if (not isinstance(activity_id, str) or not activity_id.strip()
                    or activity["activity_type"] != "FILL"
                    or activity["type"] not in {"fill", "partial_fill"}
                    or (account_id is not None and UUID(account_id) != intent.account_id)
                    or activity["symbol"] != intent.symbol or activity["side"] != intent.side
                    or not qty.is_finite() or not cumulative.is_finite()
                    or not 0 < qty <= cumulative <= observation.cumulative_filled
                    or qty.quantize(BROKER_SHARE_INCREMENT) != qty
                    or not created_at <= when <= updated_at):
                raise ValueError("Inconsistent fill activity")
            fill = (qty, cumulative, when)
            if fills.setdefault(activity_id, fill) != fill:
                raise ValueError("Conflicting fill activity identity")
        if len(page) < query["page_size"]:
            break
        token = page[-1]["id"]
        if not isinstance(token, str) or not token or token in tokens:
            raise ValueError("Invalid activity pagination")
        tokens.add(token)
        query["page_token"] = token
    else:
        raise ValueError("Fill activity pagination limit reached")

    total = Decimal(0)
    for qty, cumulative, _ in sorted(fills.values(), key=lambda fill: fill[1]):
        total += qty
        if total != cumulative:
            raise ValueError("Incomplete or overlapping fill activity")
    if total != observation.cumulative_filled:
        raise ValueError("Order aggregate and fill activity disagree")
    return fills


def _read_evidence(reader, row):
    _, account_id, client_id, symbol, side, quantity, status, filled, order_id, previous_at = row
    intent = SubmissionIntent(account_id, client_id, symbol, side.lower(), quantity, filled, order_id)
    observation = read_broker_observation(reader, intent)
    if observation is None:
        return None
    if observation.status != status and observation.status not in TRANSITIONS.get(status, ()):
        return None
    try:
        created_at = _timestamp(observation.created_at)
        updated_at = _timestamp(observation.updated_at)
        if updated_at < created_at or (previous_at is not None and updated_at < previous_at):
            return None
        if (updated_at == previous_at
                and (observation.status != status or observation.cumulative_filled != filled)):
            return None
        fills = _verified_fills(reader, intent, observation, created_at, updated_at)
        if UUID(str(reader.get_account().id)) != account_id:
            return None
    except Exception:
        return None
    return observation, updated_at, fills


def _persist_evidence(database_url, row, evidence):
    import psycopg

    request_id, account_id, _, symbol, side, _, _, _, _, _ = row
    observation, updated_at, fills = evidence
    order_id = str(observation.broker_order_id)
    kind = f"{side}_FILLED"
    events = {
        f"alpaca:{account_id}:{activity_id}": (order_id, symbol, kind, qty, when)
        for activity_id, (qty, _, when) in fills.items()
    }
    with psycopg.connect(database_url, connect_timeout=5) as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '5s'")
        cur.execute(f"""
            SELECT {COLUMNS} FROM tradebot_v2_order_reservations
            WHERE request_id = %s FOR UPDATE
        """, (request_id,))
        if cur.fetchone() != row:
            return False
        cur.execute("""
            SELECT event_id, broker_order_id, symbol, kind, quantity, recorded_at
            FROM tradebot_v2_fill_events WHERE reservation_id = %s
        """, (request_id,))
        for event_id, *fields in cur.fetchall():
            if events.get(event_id) != tuple(fields):
                return False
            del events[event_id]
        if not events and (observation.status, observation.cumulative_filled,
                           observation.broker_order_id, updated_at) == row[6:]:
            return False
        cur.executemany("""
            INSERT INTO tradebot_v2_fill_events
                (event_id, broker_order_id, symbol, kind, quantity, recorded_at,
                 account_id, reservation_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, [(event_id, *fields, account_id, request_id) for event_id, fields in events.items()])
        cur.execute("""
            UPDATE tradebot_v2_order_reservations
            SET status = %s, cumulative_filled = %s, broker_order_id = %s,
                broker_updated_at = %s, updated_at = now()
            WHERE request_id = %s RETURNING cumulative_filled
        """, (observation.status, observation.cumulative_filled,
              observation.broker_order_id, updated_at, request_id))
        if cur.fetchone()[0] != observation.cumulative_filled:
            raise RuntimeError("Reservation schema cannot store broker fill exactly")
    return True


def recover_broker_intents(database_url: str, reader: AlpacaRecoveryReader) -> list[str]:
    """Reconcile pending broker intents after restart. Return persisted request IDs.

    Unverified evidence leaves the reservation active. Persistence failures raise
    and roll back the affected intent, so callers cannot treat them as clearance.
    """
    if not database_url:
        raise ValueError("Isolated database URL required")
    import psycopg

    with psycopg.connect(database_url, connect_timeout=5) as conn, conn.cursor() as cur:
        cur.execute(f"""
            SELECT {COLUMNS} FROM tradebot_v2_order_reservations
            WHERE account_id IS NOT NULL AND status = ANY(%s)
            ORDER BY created_at, request_id
        """, (list(ACTIVE),))
        rows = cur.fetchall()
    recovered = []
    for row in rows:
        evidence = _read_evidence(reader, row)
        if evidence is not None and _persist_evidence(database_url, row, evidence):
            recovered.append(row[0])
    return recovered
