"""Read-only broker readiness adapter for the tech-swing release review.

The caller supplies an authenticated broker client. This module NEVER calls
submit_order or changes live settings. A failed broker query fails closed.
"""
from __future__ import annotations
from datetime import datetime, timezone
from backend.v20_tech_swing_broker_preflight import inspect_candidate


def broker_readiness(client, *, symbol, notional, signal_at, now=None,
                     buys_paused=True, explicit_review=False):
    try:
        account = client.get_account()
        asset = client.get_asset(symbol)
        clock = client.get_clock()
        positions = list(client.get_all_positions())
        # Use Alpaca's explicit OPEN-order filter. Never interpret a default
        # get_orders() response as proof there are no pending orders.
        if hasattr(client, "get_open_orders_for_preflight"):
            open_orders = list(client.get_open_orders_for_preflight())
        else:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus
            open_orders = list(client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN)))
        closed = {"filled", "canceled", "cancelled", "expired", "rejected",
                  "orderstatus.filled", "orderstatus.canceled",
                  "orderstatus.expired", "orderstatus.rejected"}
        if any(str(getattr(order, "status", "")).lower() in closed for order in open_orders):
            raise ValueError("open-order query returned non-open orders")
        result = inspect_candidate(symbol=symbol, account=account, asset=asset,
                                   clock=clock, positions=positions, open_orders=open_orders,
                                   notional=notional, signal_at=signal_at, now=now,
                                   buys_paused=buys_paused, explicit_review=explicit_review)
        return {"brokerReadVerified": True, **result}
    except Exception as exc:
        return {"symbol": str(symbol).upper(), "brokerReadVerified": False,
                "preflightChecksPassed": False, "liveOrdersAuthorized": False,
                "ordersSubmitted": 0, "readOnly": True,
                "reasons": ["broker_readiness_unverified"],
                "errorType": type(exc).__name__}
