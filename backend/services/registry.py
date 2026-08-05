"""Central catalogue of TradeBot subsystems.

These descriptors create explicit ownership boundaries now, allowing code to
move out of the legacy runtime one subsystem at a time without breaking API
routes, database state, worker scheduling, or trading safeguards.
"""
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class ServiceDescriptor:
    key: str
    purpose: str
    route_prefixes: Tuple[str, ...]
    can_place_orders: bool = False


SERVICE_REGISTRY = (
    ServiceDescriptor("ceo", "Executive reviews, journal and company health", ("/v12/ceo",)),
    ServiceDescriptor("board", "Automatic director voting and persisted consensus", ("/v12/board",)),
    ServiceDescriptor("evolution", "Bounded strategy and parameter evolution", ("/v8", "/evolution")),
    ServiceDescriptor("research", "Research brains, discovery and shadow evidence", ("/v7", "/shadow-trading")),
    ServiceDescriptor("reputation", "Symbol reputation and live-buy protection", ("/v10/symbol-reputation",)),
    ServiceDescriptor("execution", "Order validation and broker execution", ("/buy", "/sell"), True),
    ServiceDescriptor("risk", "Capital, position, PDT and loss safeguards", ("/banking-status",)),
    ServiceDescriptor("memory", "V13 persistent evidence-backed long-term knowledge", ("/reports", "/v13/memory")),
)
