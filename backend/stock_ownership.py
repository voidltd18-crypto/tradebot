"""Verify the first bot purchase of a stock from a known flat position."""

from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
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


def _position_quantity(broker, symbol):
    positions = [Decimal(p.qty) for p in broker.get_all_positions() if p.symbol == symbol]
    if len(positions) > 1:
        raise ValueError("Ambiguous broker position")
    return positions[0] if positions else Decimal(0)


def reserve_stock_purchase(connect, broker, symbol, notional, account_id):
    """Commit a unique client ID before submitting; never reuse an uncertain intent."""
    created = datetime.now(timezone.utc).isoformat()
    if str(broker.get_account().id) != str(account_id) or _position_quantity(broker, symbol) != 0:
        raise ValueError("BUY BLOCKED | stock ownership requires a flat starting position")
    client_id = "tradebot-stock-" + uuid4().hex
    with closing(connect()) as conn, conn:
        conn.execute("INSERT INTO stock_ownership_intents VALUES (?, ?, ?, ?, ?)",
                     (symbol, str(account_id), client_id, str(notional), created))
    return client_id


def _value(field):
    return getattr(field, "value", field)


def verified_stock_quantity(connect, broker, symbol):
    """Require exclusive, exact inventory from a fully corroborated bot order."""
    try:
        with closing(connect()) as conn:
            intent = conn.execute("""
                SELECT account_id, client_order_id, notional, created_at
                FROM stock_ownership_intents WHERE symbol = ?
            """, (symbol,)).fetchone()
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
                and str(broker.get_account().id) == account_id):
            return total
    except Exception:
        # Broker errors and database failures must never grant ownership.
        return None
    return None
