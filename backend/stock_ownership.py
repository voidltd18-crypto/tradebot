"""Verify the first bot purchase of a stock from a known flat position."""

from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import json
from uuid import uuid4

from backend.stock_broker_state import open_stock_orders


def init_stock_ownership(conn):
    from backend.stock_exit_reservation import init_exit_schema
    init_exit_schema(conn)
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


def _fill_activities(broker, created):
    activities = []
    params = {"activity_types": "FILL", "after": created, "direction": "asc", "page_size": 100}
    seen_tokens = set()
    for _ in range(10):
        page = broker.get("/account/activities", data=dict(params))
        if not isinstance(page, list) or len(page) > 100 or not all(isinstance(row, dict) for row in page):
            raise ValueError("Malformed fill activity page")
        activities.extend(page)
        if len(page) < 100:
            return activities
        token = page[-1].get("id")
        if not token or token in seen_tokens:
            raise ValueError("Fill activity pagination stalled")
        seen_tokens.add(token)
        params["page_token"] = token
    raise ValueError("Fill activity pagination limit reached")


def _flat_and_clear(broker, symbol, account_id):
    return (
        str(broker.get_account().id) == str(account_id)
        and _position_quantity(broker, symbol) == 0
        and not open_stock_orders(broker, symbol)
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

    activities = _fill_activities(broker, created)
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


def reserve_stock_purchase(connect, broker, symbol, notional, account_id, *, check_capacity=None):
    """Commit a unique client ID before submission and archive resolved intents."""
    with closing(connect()) as conn:
        intent = _intent(conn, symbol)
        others = conn.execute("SELECT symbol, account_id, client_order_id, notional, created_at "
                              "FROM stock_ownership_intents WHERE symbol != ? ORDER BY symbol", (symbol,)).fetchall()
    resolved = []
    if check_capacity is not None:
        # Production has one autonomous stock slot. Reclaim it only from a proven flat lifecycle.
        if not check_capacity():
            raise ValueError("BUY BLOCKED | no verified stock capacity")
        for other_symbol, *prior in others:
            if prior[0] != str(account_id) or not _flat_and_clear(broker, other_symbol, account_id):
                raise ValueError("BUY BLOCKED | another stock intent occupies the slot")
            proof = _resolved_buy(broker, other_symbol, prior)
            if not proof or not _flat_and_clear(broker, other_symbol, account_id):
                raise ValueError("BUY BLOCKED | another stock intent is unresolved")
            resolved.append((other_symbol, prior, proof))
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
        if check_capacity is not None:
            current = conn.execute("SELECT symbol, account_id, client_order_id, notional, created_at "
                                   "FROM stock_ownership_intents WHERE symbol != ? ORDER BY symbol", (symbol,)).fetchall()
            if current != others or conn.execute("SELECT 1 FROM stock_emergency_latch").fetchone():
                raise ValueError("BUY BLOCKED | portfolio reservation changed or emergency stop active")
            if conn.execute("SELECT 1 FROM stock_exit_intents WHERE terminal_status IS NULL").fetchone():
                raise ValueError("BUY BLOCKED | exit unresolved")
            for other_symbol, (acct, old_id, amount, stamp), proof in resolved:
                conn.execute("INSERT INTO stock_ownership_resolutions VALUES (?,?,?,?,?,?,?)",
                             (old_id, other_symbol, acct, amount, stamp, created, proof))
                conn.execute("DELETE FROM stock_ownership_intents WHERE client_order_id=?", (old_id,))
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


def verified_stock_holding(connect, broker, symbol):
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
                or _value(order.status) not in {"filled", "canceled", "expired"} or _value(order.side) != "buy"
                or order.created_at < datetime.fromisoformat(created)
                or Decimal(order.notional) != Decimal(notional)
                or not position_qty > 0):
            return None

        with closing(connect()) as conn:
            exits = dict(conn.execute("SELECT broker_id,filled FROM stock_exit_intents "
                "WHERE buy_id=? AND terminal_status IS NOT NULL AND broker_id IS NOT NULL", (client_id,)))
        expected = {str(order.id): Decimal(order.filled_qty)}
        expected.update({oid: Decimal(qty) for oid, qty in exits.items()})
        fills = {}
        for activity in _fill_activities(broker, created):
            if activity.get("symbol") not in (None, "", symbol):
                continue
            oid = activity.get("order_id")
            if (activity.get("symbol") != symbol or activity.get("activity_type") != "FILL"
                    or oid not in expected or activity.get("side") != ("buy" if oid == str(order.id) else "sell")
                    or activity.get("account_id") not in (None, account_id)):
                return None
            qty, cumulative = Decimal(activity["qty"]), Decimal(activity["cum_qty"])
            if not (qty.is_finite() and cumulative.is_finite() and 0 < qty <= cumulative):
                return None
            fill = (oid, cumulative, qty)
            if not activity["id"] or fills.setdefault(activity["id"], fill) != fill:
                return None
        totals = dict.fromkeys(expected, Decimal(0))
        for oid, cumulative, qty in sorted(fills.values()):
            totals[oid] += qty
            if totals[oid] != cumulative:
                return None
        total = expected[str(order.id)] - sum(Decimal(qty) for qty in exits.values())
        if (totals == expected and total == position_qty == _position_quantity(broker, symbol)
                and str(broker.get_account().id) == account_id
                and not open_stock_orders(broker, symbol)):
            return total, client_id
    except Exception:
        # Broker errors and database failures must never grant ownership.
        return None
    return None

def verified_stock_quantity(connect, broker, symbol):
    holding = verified_stock_holding(connect, broker, symbol)
    return holding[0] if holding else None


def reconcile_stock_intents(connect, broker, account):
    """Audit current intents without releasing them or changing the ledger."""
    with closing(connect()) as conn:
        rows = conn.execute("SELECT symbol FROM stock_ownership_intents LIMIT 101").fetchall()
    results = {"checked": 0, "verifiedHeld": 0, "resolvedFlat": 0, "unverified": 0,
               "intentLimitReached": len(rows) > 100}
    for (symbol,) in rows[:100]:
        results["checked"] += 1
        if verified_stock_holding(connect, broker, symbol):
            results["verifiedHeld"] += 1
            continue
        try:
            with closing(connect()) as conn:
                intent = _intent(conn, symbol)
            if (intent and intent[0] == str(account.id)
                    and _flat_and_clear(broker, symbol, account.id)
                    and _resolved_buy(broker, symbol, intent)
                    and _flat_and_clear(broker, symbol, account.id)):
                results["resolvedFlat"] += 1
                continue
        except Exception:
            pass
        results["unverified"] += 1
    return results
