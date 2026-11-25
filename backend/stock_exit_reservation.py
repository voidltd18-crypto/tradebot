"""Durable identity for automated stock exits and recovery from lost acknowledgements."""
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from backend.stock_broker_state import open_stock_orders


def init_exit_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS stock_exit_intents (
        client_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, buy_id TEXT NOT NULL,
        account_id TEXT NOT NULL, starting_qty TEXT NOT NULL, qty TEXT NOT NULL,
        reason TEXT NOT NULL, created TEXT NOT NULL, broker_id TEXT, filled TEXT,
        terminal_status TEXT)""")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS one_pending_stock_exit
                    ON stock_exit_intents(symbol) WHERE terminal_status IS NULL""")
    conn.execute("""CREATE TABLE IF NOT EXISTS stock_emergency_latch (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), activated TEXT NOT NULL)""")


def emergency_latched(connect):
    with closing(connect()) as conn:
        return conn.execute("SELECT 1 FROM stock_emergency_latch WHERE singleton=1").fetchone() is not None


def latch_emergency(connect):
    with closing(connect()) as conn, conn:
        conn.execute("INSERT OR IGNORE INTO stock_emergency_latch VALUES (1,?)",
                     (datetime.now(timezone.utc).isoformat(),))


def reserve_exit(connect, broker, symbol, qty, reason):
    from backend.stock_ownership import verified_stock_holding
    from backend.stock_broker_state import sellable_stock_quantity, stock_account
    # Detect even a completed competing reservation during broker verification.
    with closing(connect()) as conn:
        generation = conn.execute("SELECT COUNT(*) FROM stock_exit_intents WHERE symbol=?", (symbol,)).fetchone()[0]
    holding = verified_stock_holding(connect, broker, symbol)
    qty = Decimal(str(qty))
    if not holding or not 0 < qty <= min(holding[0], sellable_stock_quantity(broker, symbol)):
        raise ValueError("SELL BLOCKED | ownership or sellable quantity unverified")
    account_id = str(stock_account(broker).id)
    client_id = "tradebot-exit-" + uuid4().hex
    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        latest = conn.execute("SELECT COUNT(*) FROM stock_exit_intents WHERE symbol=?", (symbol,)).fetchone()[0]
        buy = conn.execute("SELECT account_id,client_order_id FROM stock_ownership_intents WHERE symbol=?", (symbol,)).fetchone()
        if latest != generation or not buy or tuple(buy) != (account_id, holding[1]):
            raise ValueError("SELL BLOCKED | holding changed")
        if conn.execute("SELECT 1 FROM stock_emergency_latch").fetchone():
            raise ValueError("SELL BLOCKED | emergency stop active")
        conn.execute("""INSERT INTO stock_exit_intents
            (client_id,symbol,buy_id,account_id,starting_qty,qty,reason,created) VALUES (?,?,?,?,?,?,?,?)""",
            (client_id, symbol, holding[1], account_id, str(holding[0]), str(qty), reason,
             datetime.now(timezone.utc).isoformat()))
    return client_id


def recover_exits(connect, broker, register):
    from backend.stock_ownership import _fill_activities, _position_quantity, _value
    with closing(connect()) as conn:
        rows = conn.execute("""SELECT client_id,symbol,account_id,starting_qty,qty,reason,created
            FROM stock_exit_intents WHERE terminal_status IS NULL""").fetchall()
    resolved = 0
    for client_id, symbol, account, starting, requested, reason, created in rows:
        try:
            if str(broker.get_account().id) != account:
                continue
            order = broker.get_order_by_client_id(client_id)
            status = _value(order.status)
            if (order.client_order_id != client_id or order.symbol != symbol or _value(order.side) != "sell"
                    or not order.id or Decimal(order.qty) != Decimal(requested)
                    or order.created_at < datetime.fromisoformat(created)):
                continue
            oid = str(order.id)
            if not register(oid, symbol, float(requested), reason, status):
                continue
            if status not in {"filled", "canceled", "expired", "rejected"} or open_stock_orders(broker, symbol):
                continue
            fills = {}
            for event in _fill_activities(broker, created):
                if not event.get("symbol"):
                    raise ValueError("missing fill symbol")
                if event["symbol"] != symbol:
                    continue
                signature = (Decimal(event["cum_qty"]), Decimal(event["qty"]), event["transaction_time"])
                if (event["activity_type"] != "FILL" or event["side"] != "sell" or event["order_id"] != oid
                        or event.get("account_id") not in (None, account) or not event["id"]
                        or datetime.fromisoformat(signature[2]) < datetime.fromisoformat(created)
                        or fills.setdefault(event["id"], signature) != signature):
                    raise ValueError("inconsistent fill evidence")
            total = Decimal(0)
            for cumulative, quantity, _ in sorted(fills.values()):
                total += quantity
                if quantity <= 0 or cumulative != total:
                    raise ValueError("incomplete fill evidence")
            if (total != Decimal(order.filled_qty) or not 0 <= total <= Decimal(requested)
                    or (status == "filled" and total != Decimal(requested))
                    or _position_quantity(broker, symbol) != Decimal(starting) - total):
                continue
            with closing(connect()) as conn, conn:
                if total:
                    accounted = conn.execute("""SELECT accounted_qty FROM pending_sell_orders
                        WHERE alpaca_order_id=? AND accounting_status='PROCESSED'""", (oid,)).fetchone()
                    if not accounted or Decimal(str(accounted[0])) != total:
                        continue
                resolved += conn.execute("""UPDATE stock_exit_intents SET broker_id=?,filled=?,terminal_status=?
                    WHERE client_id=? AND terminal_status IS NULL""", (oid, str(total), status, client_id)).rowcount
        except Exception as exc:
            print(f"STOCK EXIT UNVERIFIED | {symbol} {type(exc).__name__}", flush=True)
    return {"checked": len(rows), "resolved": resolved}
