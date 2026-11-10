"""Read-only startup recovery audit for TradeBot paper accounts.

Never submits orders, updates journal records, or changes position locks.
Invoked only behind explicit opt-in in backend.main; disabled by default.
Reject unknown, truncated or inconsistent state rather than treating it as
permission to resubmit. Broker is a separately authenticated paper client.
"""
import sqlite3
from pathlib import Path
from urllib.parse import quote

from backend.stock_sell_coordinator import stable_client_order_id
from backend.stock_exit_paper_rehearsal import KNOWN, TERMINAL


def audit_stock_sell_recovery(database_file, *, broker, max_entries=100):
    if not isinstance(max_entries, int) or isinstance(max_entries, bool) or not 0 < max_entries <= 100:
        raise ValueError("invalid recovery audit limit")
    path = Path(database_file).resolve(strict=True)
    if not path.is_file():
        raise ValueError("existing recovery database required")
    # URI-mode read only; never create a file or perform schema writes.
    uri = "file:" + quote(str(path)) + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=5) as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='stock_sell_recovery'"
        ).fetchone()
        if not exists:
            return {"readOnly": True, "ordersSubmitted": 0,
                    "journalPresent": False, "rows": [], "needsReview": False}
        rows = db.execute(
            """SELECT symbol, position_key, attempt_id, intended_qty,
                      broker_order_id, status, filled_qty
               FROM stock_sell_recovery
               WHERE status != 'VERIFIED_FLAT'
               ORDER BY symbol, position_key LIMIT ?""",
            (max_entries + 1,)
        ).fetchall()
    if len(rows) > max_entries:
        raise ValueError("recovery audit truncated; fail closed")
    assessments = []
    for symbol, position_key, attempt, intended, recorded_id, stored_status, filled in rows:
        client_id = stable_client_order_id(symbol, position_key)
        if attempt != client_id:
            assessments.append({"symbol": symbol, "positionKey": position_key,
                                "result": "ATTEMPT_ID_MISMATCH", "blocked": True})
            continue
        # The broker may be temporarily unavailable; report, never retry orders.
        try:
            order = broker.get_order_by_client_id(client_id)
            if not isinstance(order, dict) or not order.get("id"):
                outcome = "UNRESOLVED_ORDER"
            elif (str(order.get("client_order_id")) != client_id or
                  str(order.get("symbol", "")).upper() != symbol or
                  str(order.get("side", "")).lower() != "sell" or
                  (recorded_id and str(order["id"]) != str(recorded_id))):
                outcome = "BROKER_IDENTITY_MISMATCH"
            elif str(order.get("status", "")).lower() not in KNOWN:
                outcome = "UNKNOWN_ORDER_STATUS"
            else:
                position_qty = broker.fresh_position_qty(symbol)
                if position_qty is None:
                    outcome = "UNKNOWN_POSITION"
                elif str(order.get("status", "")).lower() in TERMINAL and float(position_qty) == 0:
                    outcome = "TERMINAL_AND_FLAT_REVIEW"
                else:
                    outcome = "OPEN_OR_PARTIAL_REVIEW"
        except Exception:
            outcome = "BROKER_READ_FAILED"
        assessments.append({"symbol": symbol, "positionKey": position_key,
                            "result": outcome, "blocked": True})
    return {"readOnly": True, "ordersSubmitted": 0, "journalPresent": True,
            "rows": assessments, "needsReview": bool(assessments)}
