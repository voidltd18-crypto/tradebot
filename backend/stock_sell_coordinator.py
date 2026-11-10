"""Opt-in, broker-agnostic STOCK sell coordinator for future paper integration.

NEVER called by the production worker. No credentials, Alpaca SDK, network
access or live connection are created here. Caller must inject broker and
shared durable journal, with authoritative position/order reads.

Crucial: a DB reservation always precedes submission, and an uncertain
submission NEVER causes an automatic second submission.
"""
import hashlib
from decimal import Decimal
from backend.stock_exit_state_store import _identity
from backend.stock_sell_recovery_postgres import _qty

# Alpaca client_order_id is bounded; use a stable digest, not a timestamp.
def stable_client_order_id(symbol, position_key):
    symbol, position_key = _identity(symbol, position_key)
    digest = hashlib.sha256((symbol + "\0" + position_key).encode()).hexdigest()[:32]
    return "tb-stock-sell-" + digest


class SafeStockSellCoordinator:
    """Injected broker contract:

    broker.fresh_position_qty(symbol) -> authoritative quantity (or raises)
    broker.list_open_orders(symbol) -> full current orders (or raises)
    broker.get_order_by_client_id(client_id) -> order or None (or raises)
    broker.submit_sell(symbol, qty, client_order_id=...) -> order (or raises)

    Broker adapter must query ALL relevant orders before ever returning None,
    including recently completed orders. Snapshot freshness/market/PDT checks
    remain caller responsibilities and are NOT established by this class.
    """

    def __init__(self, *, journal, broker):
        self.journal = journal
        self.broker = broker

    def propose(self, *, symbol, position_key, quantity, eligible=False):
        """Explicitly non-executable candidate gate; no hidden buy/sell logic."""
        symbol, position_key = _identity(symbol, position_key)
        qty = _qty(quantity)
        if eligible is not True:
            return {"status": "BLOCKED_PRECHECK", "submitted": False}
        client_id = stable_client_order_id(symbol, position_key)
        # First look up the journal, so an existing uncertain request is
        # NEVER sent again, even if the broker later appears empty.
        prior = self.journal.snapshot(symbol, position_key)
        if prior["found"]:
            return {"status": "RECONCILE_EXISTING", "submitted": False,
                    "clientOrderId": client_id}
        # These are authoritative adapter reads and must throw on failures.
        position = _qty(self.broker.fresh_position_qty(symbol), allow_zero=True)
        requested = min(qty, position)
        if requested == 0 or requested != qty:
            return {"status": "BLOCKED_POSITION_MISMATCH", "submitted": False}
        orders = self.broker.list_open_orders(symbol)
        if not isinstance(orders, list):
            raise ValueError("unverified open orders")
        if any(not isinstance(x, dict) or x.get("side") != "buy" and
               x.get("side") != "sell" for x in orders):
            raise ValueError("unverified order format")
        if any(x.get("side") == "sell" for x in orders):
            return {"status": "BLOCKED_EXISTING_SELL", "submitted": False}
        # Refuse an attempt if the broker already knows this deterministic ID.
        known = self.broker.get_order_by_client_id(client_id)
        if known is not None:
            return {"status": "BROKER_ORDER_EXISTS", "submitted": False,
                    "clientOrderId": client_id}
        # A durable claim MUST commit successfully before touching the broker.
        if not self.journal.reserve_before_submit(
                symbol, position_key, client_id, requested):
            return {"status": "RESERVATION_BLOCKED", "submitted": False}
        try:
            order = self.broker.submit_sell(
                symbol, requested, client_order_id=client_id)
        except Exception:
            # A timeout or exception may follow a broker-accepted order.
            # Preserve the reservation; no resubmit, even after restart.
            self.journal.mark_unknown(symbol, position_key)
            return {"status": "UNKNOWN_BROKER_OUTCOME", "submitted": False,
                    "clientOrderId": client_id}
        if not isinstance(order, dict) or not order.get("id") or (
                order.get("client_order_id") != client_id or
                str(order.get("symbol") or "").upper() != symbol or
                str(order.get("side") or "").lower() != "sell"):
            self.journal.mark_unknown(symbol, position_key)
            return {"status": "UNKNOWN_BROKER_ACK", "submitted": False,
                    "clientOrderId": client_id}
        try:
            self.journal.broker_ack(
                symbol, position_key, client_id, str(order["id"]))
        except Exception:
            # Broker may have accepted the order; reservation stays blocked.
            return {"status": "ACK_PERSISTENCE_UNCERTAIN", "submitted": True,
                    "clientOrderId": client_id}
        return {"status": "ACKNOWLEDGED_NOT_FILLED", "submitted": True,
                "clientOrderId": client_id, "brokerOrderId": str(order["id"])}

    def recover(self, *, symbol, position_key):
        """Read-only broker reconciliation. Does NOT grant new order permission."""
        symbol, position_key = _identity(symbol, position_key)
        state = self.journal.snapshot(symbol, position_key)
        if not state["found"]:
            return {"status": "NO_JOURNAL_RECORD", "submitted": False}
        cid = stable_client_order_id(symbol, position_key)
        # Missing broker order means unknown, not permission to retry.
        order = self.broker.get_order_by_client_id(cid)
        if not isinstance(order, dict) or not order.get("id") or (
                order.get("client_order_id") != cid or
                str(order.get("symbol") or "").upper() != symbol or
                str(order.get("side") or "").lower() != "sell"):
            return {"status": "UNRESOLVED_BROKER_ORDER", "submitted": False}
        fresh_qty = self.broker.fresh_position_qty(symbol)
        result = self.journal.reconcile(
            symbol, position_key, broker_order_id=str(order["id"]),
            order_status=str(order.get("status") or ""),
            filled_qty=order.get("filled_qty"),
            fresh_position_qty=fresh_qty,
        )
        return {"status": result["status"], "submitted": False,
                "clientOrderId": cid, "blockedFromResubmit": True}
