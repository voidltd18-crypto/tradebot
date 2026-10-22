"""Offline, illustrative trailing exit replay. No broker or live trading calls."""
import pytest


def simulate(prices, entry, start_pct, giveback_pct, confirmation_checks=1):
    peak = entry
    breaches = 0
    for index, price in enumerate(prices):
        peak = max(peak, price)
        trigger = entry * (1 + start_pct / 100)
        if peak < trigger:
            continue
        floor = peak * (1 - giveback_pct / 100)
        if price > floor:
            breaches = 0
            continue
        breaches += 1
        if breaches >= confirmation_checks:
            return {"index": index, "price": price, "peak": peak, "floor": floor}
    return None


def test_flnc_screenshot_current_unarmed():
    # Sparse screenshot anchors, not the full historical quote path.
    observed = [5.87, 5.96, 5.92]
    assert simulate(observed, 5.87, 2.15, 0.73) is None


def test_flnc_screenshot_tighter_trail_crosses_floor():
    observed = [5.87, 5.96, 5.92]
    result = simulate(observed, 5.87, 1.0, 0.5)
    assert result is not None
    assert result["price"] == 5.92
    assert result["floor"] == pytest.approx(5.9302)


def test_runner_grace_requires_another_observation():
    # The real runner grants grace only under additional P&L, momentum,
    # peak and shallow-breach conditions; this is a simplified upper bound.
    assert simulate([5.87, 5.96, 5.92], 5.87, 1.0, 0.5, confirmation_checks=2) is None
    assert simulate([5.87, 5.96, 5.92, 5.91], 5.87, 1.0, 0.5, confirmation_checks=2)["price"] == 5.91
