"""Read-only Alpaca verification for a previously recorded submission intent."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from backend.tradebot_v2.engine import TECH_UNIVERSE


class AlpacaOrderReader(Protocol):
    def get_account(self): ...
    def get_order_by_client_id(self, client_id: str): ...


@dataclass(frozen=True)
class SubmissionIntent:
    """Identity and quantity recorded locally before any submission."""

    account_id: UUID
    client_order_id: str
    symbol: str
    side: str
    quantity: Decimal
    cumulative_filled: Decimal = Decimal(0)
    broker_order_id: UUID | None = None


@dataclass(frozen=True)
class BrokerObservation:
    broker_order_id: UUID
    status: str
    cumulative_filled: Decimal


# Only states with an unambiguous meaning in the local lifecycle are mapped.
STATES = {
    "new": "accepted",
    "accepted": "accepted",
    "partially_filled": "partially_filled",
    "filled": "filled",
    "canceled": "cancelled",
    "expired": "cancelled",
    "rejected": "rejected",
}


def read_broker_observation(
    reader: AlpacaOrderReader, intent: SubmissionIntent
) -> BrokerObservation | None:
    """Return verified evidence, or None to keep the outcome unresolved.

    This lookup makes no writes and does not decide whether to release a
    reservation. An order changing between reads must be handled by the
    caller's transactional lifecycle and fill reconciliation.
    """
    if (not isinstance(intent.client_order_id, str) or not intent.client_order_id.strip()
            or intent.client_order_id.startswith(("offline-", "sim-"))
            or intent.symbol not in TECH_UNIVERSE or intent.side not in {"buy", "sell"}
            or not isinstance(intent.account_id, UUID)):
        return None
    try:
        if (not intent.quantity.is_finite() or not intent.cumulative_filled.is_finite()
                or not 0 <= intent.cumulative_filled <= intent.quantity or intent.quantity <= 0):
            return None
        if UUID(str(reader.get_account().id)) != intent.account_id:
            return None
        order = reader.get_order_by_client_id(intent.client_order_id)
        order_id = UUID(str(order.id))
        side = getattr(order.side, "value", order.side)
        status = STATES.get(getattr(order.status, "value", order.status))
        quantity = Decimal(str(order.qty))
        filled = Decimal(str(order.filled_qty))
        if (order.client_order_id != intent.client_order_id or order.symbol != intent.symbol
                or side != intent.side or quantity != intent.quantity
                or (intent.broker_order_id is not None and order_id != intent.broker_order_id)
                or status is None or not filled.is_finite()
                or not intent.cumulative_filled <= filled <= quantity):
            return None
        if status in {"accepted", "rejected"} and filled != 0:
            return None
        if (status == "filled") != (filled == quantity):
            return None
        if status == "partially_filled" and filled == 0:
            return None
    except Exception:
        # A missing order, timeout or malformed response leaves it unresolved.
        return None
    return BrokerObservation(order_id, status, filled)
