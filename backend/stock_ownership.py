"""Verify the first bot purchase of a stock from a known flat position."""

from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import json
from uuid import uuid4


def init_stock_ownership(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_ownership_intents (
            symbol TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            client_order_id TEXT NOT NULL UNIQUE,
            notional TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_ownership_resolutions (
            client_order_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            account_id TEXT NOT NULL,
            notional TEXT NOT NULL,
            created_at TEXT NOT NULL,
            resolved_at TEXT NOT NULL,
            evidence TEXT NOT NULL
        )
    """)


def _position_quantity(broker, symbol):
    positions = [Decimal(p.qty) for p in broker.get_all_positions() if p.symbol == symbol]
    if len(positions) > 1:
        raise ValueError("Ambiguous broker position")
    return positions[0] if positions else Decimal(0)


def _intent(conn, symbol):
    return conn.execute(
        "SELECT account_id, client_order_id, notional, created_at "
        "FROM stock_ownership_intents WHERE symbol = ?", (symbol,),
    ).fetchone()


def _has_open_orders(broker, symbol):
    orders = broker.get("/orders", data={"status": "open", "symbols": symbol, "limit": 1})
    if not isinstance(orders, list):
        raise ValueError("Open broker orders could not be verified")
    return bool(orders)


def _flat_and_clear(broker, symbol, account_id):
    return (
        str(broker.get_account().id) == str(account_id)
        and _position_quantity(broker, symbol) == 0
        and not _has_open_orders(broker, symbol)
    )


def _resolved_buy(broker, symbol, intent):
    account_id, client_id, notional, created = intent
    order = broker.get_order_by_client_id(client_id)
    status = _value(order.status)
    if (order.client_order_id != client_id or order.symbol != symbol
            or _value(order.side) != "buy" or order.created_at < datetime.fromisoformat(created)
            or Decimal(order.notional) != Decimal(notional)
            or status not in {"filled", "canceled", "expired", "rejected"}):
        return None

    filled = Decimal(order.filled_qty)
    if not filled.is_finite() or filled < 0 or (status == "filled" and filled == 0):
        return None

    # Refuse truncated history, missing IDs, and buy fills from other orders.
    activities = broker.get("/account/activities", data={
        "activity_types": "FILL", "after": created, "direction": "asc", "page_size": 100,
    })
    if not isinstance(activities, list) or len(activities) >= 100:
        return None
    fills = {}
    for activity in activities:
        if activity.get("symbol") not in (None, "", symbol):
            continue
        side = activity.get("side")
        order_id = activity.get("order_id")
        if (activity.get("symbol") != symbol or activity.get("activity_type") != "FILL"
                or activity.get("account_id") not in (None, account_id)
                or not order_id or side not in {"buy", "sell"}
                or (side == "buy") != (order_id == str(order.id))):
            return None
        qty, cumulative = Decimal(activity["qty"]), Decimal(activity["cum_qty"])
        if not (qty.is_finite() and cumulative.is_finite() and 0 < qty <= cumulative):
            return None
        execution = (order_id, side, cumulative, qty, activity["transaction_time"])
        if not activity["id"] or fills.setdefault(activity["id"], execution) != execution:
            return None

    cumulative_by_order = {}
    inventory = Decimal(0)
    for order_id, side, cumulative, qty, stamp in sorted(
        fills.values(), key=lambda execution: (
            datetime.fromisoformat(execution[4]), execution[2]
        ),
    ):
        order_total = cumulative_by_order.get(order_id, Decimal(0)) + qty
        if order_total != cumulative or datetime.fromisoformat(stamp) < datetime.fromisoformat(created):
            return None
        cumulative_by_order[order_id] = order_total
        inventory += qty if side == "buy" else -qty
        if inventory < 0:
            return None
    if cumulative_by_order.get(str(order.id), Decimal(0)) != filled or inventory != 0:
        return None
    return json.dumps({"status": status, "orderId": str(order.id), "filledQty": str(filled),
                       "fills": list(fills.items())}, default=str)


def reserve_stock_purchase(connect, broker, symbol, notional, account_id):
    """Commit a unique client ID before submission and archive resolved intents."""
    with closing(connect()) as conn:
        intent = _intent(conn, symbol)
    if not _flat_and_clear(broker, symbol, account_id):
        raise ValueError("BUY BLOCKED | stock ownership requires a flat position and no open orders")
    evidence = None
    if intent is not None:
        if intent[0] == str(account_id):
            try:
                evidence = _resolved_buy(broker, symbol, intent)
            except Exception as exc:
                raise ValueError("BUY BLOCKED | previous stock intent could not be verified") from exc
        if evidence is None or not _flat_and_clear(broker, symbol, account_id):
            raise ValueError("BUY BLOCKED | previous stock intent is unresolved")

    client_id = "tradebot-stock-" + uuid4().hex
    created = datetime.now(timezone.utc).isoformat()
    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if _intent(conn, symbol) != intent:
            raise ValueError("BUY BLOCKED | stock intent changed during reconciliation")
        if intent is not None:
            old_account, old_id, old_notional, old_created = intent
            conn.execute("INSERT INTO stock_ownership_resolutions VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (old_id, symbol, old_account, old_notional, old_created, created, evidence))
            conn.execute("DELETE FROM stock_ownership_intents WHERE symbol = ?", (symbol,))
        conn.execute("INSERT INTO stock_ownership_intents VALUES (?, ?, ?, ?, ?)",
                     (symbol, str(account_id), client_id, str(notional), created))
    return client_id


def _value(field):
    return getattr(field, "value", field)


def verified_stock_quantity(connect, broker, symbol):
    """Require exclusive, exact inventory from a fully corroborated bot order."""
    try:
        with closing(connect()) as conn:
            intent = _intent(conn, symbol)
        if intent is None:
            return None
        account_id, client_id, notional, created = intent
        if str(broker.get_account().id) != account_id:
            return None
        position_qty = _position_quantity(broker, symbol)
        order = broker.get_order_by_client_id(client_id)
        if (order.client_order_id != client_id or order.symbol != symbol
                or _value(order.status) != "filled" or _value(order.side) != "buy"
                or order.created_at < datetime.fromisoformat(created)
                or Decimal(order.notional) != Decimal(notional)
                or position_qty != Decimal(order.filled_qty) or not position_qty > 0):
            return None

        # Read the full bounded window. Missing or ambiguous activity fails closed.
        activities = broker.get("/account/activities", data={
            "after": created, "direction": "asc", "page_size": 100,
        })
        if not isinstance(activities, list) or len(activities) >= 100:
            return None
        fills = {}
        for activity in activities:
            if activity.get("symbol") not in (None, "", symbol):
                continue
            if (activity.get("symbol") != symbol or activity.get("activity_type") != "FILL"
                    or activity.get("order_id") != str(order.id) or activity.get("side") != "buy"
                    or activity.get("account_id") not in (None, account_id)):
                return None
            qty, cumulative = Decimal(activity["qty"]), Decimal(activity["cum_qty"])
            if not (qty.is_finite() and cumulative.is_finite() and 0 < qty <= cumulative):
                return None
            fill = (cumulative, qty)
            if not activity["id"] or fills.setdefault(activity["id"], fill) != fill:
                return None
        total = Decimal(0)
        for cumulative, qty in sorted(fills.values()):
            total += qty
            if total != cumulative:
                return None
        if (total == position_qty == _position_quantity(broker, symbol)
                and str(broker.get_account().id) == account_id
                and not _has_open_orders(broker, symbol)):
            return total
    except Exception:
        # Broker errors and database failures must never grant ownership.
        return None
    return None
