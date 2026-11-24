"""Durable restart gate for isolated TradeBot 2.0.

By default the gate only reads local reservations. With an explicit broker
reader it first attempts to persist corroborated recovery evidence.
"""
from dataclasses import dataclass
from backend.tradebot_v2.durable_broker_recovery import AlpacaRecoveryReader, recover_broker_intents
from backend.tradebot_v2.durable_reservations import recover_active_offline


@dataclass(frozen=True)
class RecoveryPreflight:
    allowed: bool
    reason: str
    active_count: int


def check_restart_preflight(database_url: str, *, reader=recover_active_offline,
                            broker_reader: AlpacaRecoveryReader | None = None) -> RecoveryPreflight:
    if not isinstance(database_url, str) or not database_url.strip():
        return RecoveryPreflight(False, "Isolated durable store unavailable", 0)
    try:
        if broker_reader is not None:
            recover_broker_intents(database_url, broker_reader)
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
