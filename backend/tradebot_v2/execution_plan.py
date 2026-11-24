"""Offline order planning only. No broker SDK, network calls, or order submission.

A plan is NOT an authorization to trade. Live execution requires a separately
reviewed broker adapter, durable atomic reservations and explicit approval.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

from backend.tradebot_v2.engine import Position, OrderRecord, entry_gate, TECH_UNIVERSE


@dataclass(frozen=True)
class Plan:
    permitted: bool
    symbol: str
    side: str
    quantity: Decimal
    reason: str


def _qty(value):
    try:
        q = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return q if q.is_finite() and q > 0 else None


def plan_buy(symbol, quantity, positions, orders, now=None, *,
             market_data_verified=False, durable_reservation_verified=False):
    """Fail closed; never permit live buying. Only produce a reviewable plan."""
    symbol = symbol.strip().upper() if isinstance(symbol, str) else ""
    q = _qty(quantity)
    if symbol not in TECH_UNIVERSE or q is None:
        return Plan(False, symbol, "BUY", Decimal(0), "Invalid symbol or quantity")
    if not market_data_verified or not durable_reservation_verified:
        return Plan(False, symbol, "BUY", q, "Market data or atomic reservation unverified")
    try:
        gate = entry_gate(symbol, positions, orders, now)
    except (TypeError, ValueError, AttributeError):
        return Plan(False, symbol, "BUY", q, "Broker safety gate failed")
    if gate.status != "AMBER" or gate.reason != "Entry safeguards passed; price signal not yet verified":
        return Plan(False, symbol, "BUY", q, gate.reason)
    return Plan(False, symbol, "BUY", q, "Research plan only; live order submission disabled")


def plan_sell(symbol, quantity, owned_quantity, broker_quantity, *,
              verified_bot_origin=False, ledger_reconciled=False,
              market_data_verified=False, position_provenance_verified=False):
    """Manual shares can never be treated as bot inventory by this planner."""
    symbol = symbol.strip().upper() if isinstance(symbol, str) else ""
    q, owned, broker = _qty(quantity), _qty(owned_quantity), _qty(broker_quantity)
    if symbol not in TECH_UNIVERSE or q is None or owned is None or broker is None:
        return Plan(False, symbol, "SELL", Decimal(0), "Invalid or unavailable inventory")
    if not (verified_bot_origin and ledger_reconciled and market_data_verified):
        return Plan(False, symbol, "SELL", q, "Bot ownership or market data unverified")
    if q > owned or q > broker:
        return Plan(False, symbol, "SELL", q, "Quantity exceeds verified inventory")
    if not position_provenance_verified:
        return Plan(False, symbol, "SELL", q, "Order execution disabled; current shares have ambiguous ownership")
    return Plan(False, symbol, "SELL", q, "Research plan only; live order submission disabled")
