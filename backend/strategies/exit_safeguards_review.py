"""Review-only pure functions for stock exit safeguards.

Not wired into the live trading loop. No broker calls or side effects.
All timestamps are UTC epoch seconds; all prices are USD.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class Fill:
    side: str
    qty: Decimal
    price: Decimal


def realised_pnl_usd(entry: Fill, exit: Fill) -> Decimal:
    """Compute matched long-trade realised P&L from broker fills, not quote estimates.

    Requires an exact matched quantity. Partial fills must be allocated to
    matched lots upstream; this function intentionally rejects ambiguity.
    """
    if entry.side.lower() != "buy" or exit.side.lower() != "sell":
        raise ValueError("Expected a long entry buy and exit sell")
    if entry.qty <= 0 or exit.qty <= 0 or entry.qty != exit.qty:
        raise ValueError("Positive exactly matched quantities required")
    if entry.price <= 0 or exit.price <= 0:
        raise ValueError("Fill prices must be positive")
    return (exit.price - entry.price) * exit.qty


def loss_cooldown_active(
    now_epoch: float, last_losing_exit_epoch: Optional[float],
    cooldown_seconds: int = 900,
) -> bool:
    """Whether to block NEW automatic entries after a confirmed losing fill.

    The caller must obtain last_losing_exit_epoch from broker-reconciled fills.
    This function must never gate stop-loss or other exit processing.
    """
    if cooldown_seconds < 0:
        raise ValueError("Cooldown must not be negative")
    if last_losing_exit_epoch is None:
        return False
    elapsed = now_epoch - last_losing_exit_epoch
    return 0 <= elapsed < cooldown_seconds


def quote_requires_review(
    candidate_price: Decimal, reference_price: Decimal,
    max_deviation_pct: Decimal = Decimal("2"),
) -> bool:
    """Flag questionable entry/scanner quotes; never suppress protective exits.

    This is an advisory filter, not a market-data validation mechanism.
    A second independently timestamped market quote is still required.
    """
    if candidate_price <= 0 or reference_price <= 0:
        return True
    if max_deviation_pct <= 0:
        raise ValueError("Deviation threshold must be positive")
    deviation_pct = abs(candidate_price - reference_price) / reference_price * 100
    return deviation_pct > max_deviation_pct
