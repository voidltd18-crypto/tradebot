"""Pure, read-only rehearsal of stock exit permission and broker order lifecycle.

NO Alpaca client, networking, credential access or order submission. The
function assesses whether a hypothetical sell could be considered and
reconciles an externally supplied broker snapshot. It cannot authorize live
trading. Production broker/account checks must remain authoritative.
"""
from datetime import datetime, timezone
from math import isfinite

WORKING = frozenset({"new", "accepted", "pending_new", "partially_filled",
                     "pending_cancel", "pending_replace", "accepted_for_bidding",
                     "held", "stopped", "suspended", "calculated"})
TERMINAL = frozenset({"filled", "canceled", "expired", "rejected", "replaced"})
KNOWN = WORKING | TERMINAL


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamps must be ISO-8601 strings with offsets")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timezone offset required")
    return result.astimezone(timezone.utc)


def rehearse_exit_gate(
    *, symbol, position_qty, candidate_exit, quote_timestamp, now,
    market_open, account_sell_allowed, existing_orders,
    max_quote_age_seconds=15,
):
    """Return diagnostics, never broker commands.

    A working SELL order blocks a repeated exit. Even a terminal prior
    order must be reconciled with the authoritative CURRENT position qty
    before a fresh attempt. This function assumes input position quantity
    already comes from a fresh broker reconciliation: it does not prove it.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("symbol is required")
    symbol = symbol.strip().upper()
    if any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for c in symbol):
        raise ValueError("invalid symbol")
    try:
        qty = float(position_qty)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid quantity") from exc
    if not isfinite(qty) or qty < 0:
        raise ValueError("quantity must be finite and nonnegative")
    if not isinstance(candidate_exit, bool):
        raise ValueError("candidate_exit must be boolean")
    if not isinstance(market_open, bool) or not isinstance(account_sell_allowed, bool):
        raise ValueError("broker gate flags must be boolean")
    if not isinstance(existing_orders, (list, tuple)) or len(existing_orders) > 100:
        raise ValueError("existing_orders must be a bounded list")
    if not isinstance(max_quote_age_seconds, (int, float)) or isinstance(max_quote_age_seconds, bool) or not isfinite(max_quote_age_seconds) or not 0 < max_quote_age_seconds <= 120:
        raise ValueError("invalid quote age maximum")
    timestamp = _timestamp(quote_timestamp)
    current = _timestamp(now)
    age = (current - timestamp).total_seconds()
    if age < 0:
        raise ValueError("future-dated quote")
    working_sells = []
    blocking_unknown = []
    for item in existing_orders:
        if not isinstance(item, dict):
            raise ValueError("invalid order record")
        if str(item.get("symbol", "")).upper() != symbol:
            continue
        side = str(item.get("side", "")).lower()
        status = str(item.get("status", "")).lower()
        if side not in {"buy", "sell"} or status not in KNOWN:
            blocking_unknown.append(item.get("id"))
            continue  # unknown order status fails closed
        if side == "sell" and status in WORKING:
            working_sells.append(item.get("id"))
    reasons = []
    if not candidate_exit:
        reasons.append("NO_EXIT_SIGNAL")
    if qty == 0:
        reasons.append("NO_POSITION")
    if age > max_quote_age_seconds:
        reasons.append("STALE_PRICE")
    if not market_open:
        reasons.append("MARKET_CLOSED")
    if not account_sell_allowed:
        reasons.append("ACCOUNT_RESTRICTION")
    if working_sells:
        reasons.append("EXISTING_WORKING_SELL")
    if blocking_unknown:
        reasons.append("UNKNOWN_ORDER_STATUS")
    return {
        "readOnly": True, "ordersSubmitted": 0,
        "symbol": symbol, "positionQty": qty,
        "quoteAgeSeconds": round(age, 3),
        "wouldPassPreflight": not reasons,
        "reasons": reasons,
        "workingSellIds": working_sells,
        "unknownOrderIds": blocking_unknown,
        "requiresFreshBrokerReconciliation": True,
        "brokerOrderCreated": False,
        "note": "Hypothetical preflight only; never authorizes or places orders",
    }


def reconcile_order_updates(updates):
    """Validate a chronological, cumulative filled_qty sequence.

    Multiple statuses are allowed with increasing cumulative fills.
    Reject fills greater than requested quantity and regression of fills.
    """
    if not isinstance(updates, (list, tuple)) or not 1 <= len(updates) <= 100:
        raise ValueError("need 1..100 order snapshots")
    initial_id = None
    total_qty = None
    filled = 0.0
    last_time = None
    statuses = []
    for update in updates:
        if not isinstance(update, dict):
            raise ValueError("invalid snapshot")
        order_id = str(update.get("id") or "")
        status = str(update.get("status") or "").lower()
        try:
            qty = float(update.get("qty"))
            cumulative = float(update.get("filled_qty"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("bad quantity") from exc
        timestamp = _timestamp(update.get("timestamp"))
        if not order_id or status not in KNOWN or not all(map(isfinite, (qty, cumulative))):
            raise ValueError("invalid order identity/status/quantity")
        if qty <= 0 or cumulative < 0 or cumulative > qty:
            raise ValueError("invalid filled quantity")
        if initial_id is None:
            initial_id, total_qty = order_id, qty
        if (order_id != initial_id or abs(qty - total_qty) > 1e-8 or
                cumulative + 1e-8 < filled or
                (last_time is not None and timestamp <= last_time)):
            raise ValueError("order identity, fills, or timestamps inconsistent")
        if statuses and statuses[-1] in TERMINAL:
            raise ValueError("order updated after terminal status")
        if status == "filled" and abs(cumulative - qty) > 1e-8:
            raise ValueError("filled status requires fully filled quantity")
        filled, last_time = cumulative, timestamp
        statuses.append(status)
    return {"readOnly": True, "ordersSubmitted": 0,
            "orderId": initial_id, "status": statuses[-1],
            "requestedQty": total_qty, "filledQty": filled,
            "remainingQty": round(max(0, total_qty - filled), 8),
            "terminal": statuses[-1] in TERMINAL,
            "needsPositionRefresh": True}
