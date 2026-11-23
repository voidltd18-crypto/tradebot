"""Read-only durable restart preflight for isolated TradeBot 2.0.

Never submits broker orders or changes database rows. A database outage,
unknown submission, or any active reservation blocks simulated new buys.
The check alone does NOT make an in-memory simulator durable or live-ready.
"""
from dataclasses import dataclass
from backend.tradebot_v2.durable_reservations import recover_active_offline


@dataclass(frozen=True)
class RecoveryPreflight:
    allowed: bool
    reason: str
    active_count: int


def check_restart_preflight(database_url: str, *, reader=recover_active_offline) -> RecoveryPreflight:
    if not isinstance(database_url, str) or not database_url.strip():
        return RecoveryPreflight(False, "Isolated durable store unavailable", 0)
    try:
        outstanding = reader(database_url)
        if not isinstance(outstanding, list):
            return RecoveryPreflight(False, "Invalid durable recovery response", 0)
        for order in outstanding:
            if (not isinstance(order.request_id, str) or not order.request_id
                    or not isinstance(order.symbol, str) or not order.symbol
                    or order.status not in {"reserved", "submitted_unknown",
                                         "accepted", "partially_filled"}):
                return RecoveryPreflight(False, "Unverifiable outstanding reservation", len(outstanding))
    except Exception:
        return RecoveryPreflight(False, "Durable recovery failed; orders blocked", 0)
    if outstanding:
        return RecoveryPreflight(
            False, "Outstanding durable reservations require broker reconciliation", len(outstanding)
        )
    return RecoveryPreflight(True, "No outstanding durable reservations", 0)
