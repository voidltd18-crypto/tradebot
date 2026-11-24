"""Recovery-gated offline workflow. No broker operations or ownership writes."""

from dataclasses import dataclass

from backend.tradebot_v2.durable_reservations import reserve_offline
from backend.tradebot_v2.recovery_preflight import check_restart_preflight
from backend.tradebot_v2.simulation_gate import SimulationDecision, simulate_buy, simulate_sell


@dataclass(frozen=True)
class _DurableSimulator:
    database_url: str
    shutdown: bool = False

    def reserve(self, symbol, side, quantity, request_id):
        try:
            order = reserve_offline(
                self.database_url, request_id, symbol, side, quantity, require_idle=True
            )
        except Exception:
            raise RuntimeError("Durable reservation unavailable or blocked") from None
        if order.status != "reserved":
            raise RuntimeError("Request already processed")
        return order


def simulate_buy_after_recovery(*, database_url: str, recovery_reader=None,
                                simulator=None, **buy_kwargs):
    """Use the existing account and signal checks before a durable offline buy.

    An explicitly supplied simulator supports in-memory rehearsals after a
    read-only recovery check. By default admission and reservation are atomic.
    """
    if simulator is not None:
        options = {"reader": recovery_reader} if recovery_reader is not None else {}
        preflight = check_restart_preflight(database_url, **options)
        if not preflight.allowed:
            return SimulationDecision("RED", "Durable recovery blocked: " + preflight.reason)
    else:
        simulator = _DurableSimulator(database_url)
    return simulate_buy(simulator=simulator, **buy_kwargs)


def simulate_sell_after_recovery(*, database_url: str, **sell_kwargs):
    """Reserve an offline sell only after the existing ownership checks."""
    return simulate_sell(
        simulator=_DurableSimulator(database_url), require_exclusive_ownership=True, **sell_kwargs
    )
