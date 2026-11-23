"""Durable-preflight-gated OFFLINE buy simulation.

The preflight is intentionally rechecked on every call. This remains
research-only: it neither submits broker orders nor atomically reserves
in Neon. A future execution adapter MUST use a single transactional
reservation and must independently verify broker account state.
"""
from backend.tradebot_v2.recovery_preflight import check_restart_preflight
from backend.tradebot_v2.simulation_gate import SimulationDecision, simulate_buy


def simulate_buy_after_recovery(*, database_url: str, recovery_reader=None, **buy_kwargs):
    """Fail closed before an in-memory buy if durable recovery is uncertain."""
    if recovery_reader is None:
        preflight = check_restart_preflight(database_url)
    else:
        preflight = check_restart_preflight(database_url, reader=recovery_reader)
    if not preflight.allowed:
        return SimulationDecision("RED", "Durable recovery blocked: " + preflight.reason)
    return simulate_buy(**buy_kwargs)
