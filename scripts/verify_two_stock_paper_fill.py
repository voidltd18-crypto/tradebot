#!/usr/bin/env python3
"""Explicitly opted-in Alpaca PAPER-only stock fill verification.

This is an isolated diagnostic, not an integration with TradeBot's production
TradingClient. No production settings, database, stock pause, or orders change.
Run ONLY with a separate Alpaca paper account you control.
"""
import argparse
import os
import sys
import time

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="TSLA", choices=("TSLA", "SPCX"))
    parser.add_argument("--execute-paper", action="store_true", help="Permit a $2 paper-only BUY; otherwise dry-run")
    parser.add_argument("--confirm", default="", help="Must equal PAPER-ONLY to submit")
    args = parser.parse_args()
    if not args.execute_paper or args.confirm != "PAPER-ONLY":
        print("DRY RUN: no order submitted. For a paper-only $2 buy, pass --execute-paper --confirm PAPER-ONLY.")
        return 0

    key = os.environ.get("ALPACA_PAPER_API_KEY", "").strip()
    secret = os.environ.get("ALPACA_PAPER_API_SECRET", "").strip()
    if not key or not secret:
        print("BLOCKED: separate ALPACA_PAPER_API_KEY / ALPACA_PAPER_API_SECRET required.", file=sys.stderr)
        return 2

    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
    from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
    from backend.v19_two_stock_asset_preflight import check_from_broker

    client = TradingClient(key, secret, paper=True)
    account = client.get_account()
    if str(getattr(account, "status", "")).upper() != "ACTIVE":
        print("BLOCKED: paper account is not ACTIVE.")
        return 2
    if not client.get_clock().is_open:
        print("BLOCKED: broker stock-market clock is closed. No order submitted.")
        return 2
    eligible = check_from_broker(client, args.symbol)
    if not eligible["eligible"]:
        print("BLOCKED: broker asset preflight failed:", eligible["reasons"])
        return 2
    # Require a clean, isolated test account to avoid mixing unrelated holdings.
    positions = client.get_all_positions()
    open_orders = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
    if positions or open_orders:
        print("BLOCKED: test paper account has positions or open orders; use an empty paper account.")
        return 2
    if float(getattr(account, "buying_power", 0) or 0) < 2.0:
        print("BLOCKED: paper buying power below $2.")
        return 2

    order = client.submit_order(MarketOrderRequest(
        symbol=args.symbol, notional=2.00, side=OrderSide.BUY, time_in_force=TimeInForce.DAY
    ))
    order_id = str(order.id)
    print("PAPER ONLY BUY SUBMITTED; acknowledgement is NOT proof of fill.")
    print("order_id:", order_id)
    for attempt in range(30):
        current = client.get_order_by_id(order_id)
        status = str(getattr(current.status, "value", current.status)).lower()
        filled_qty = str(getattr(current, "filled_qty", "0") or "0")
        filled_price = str(getattr(current, "filled_avg_price", "") or "")
        print(f"paper status={status} filled_qty={filled_qty} filled_avg_price={filled_price}")
        if status == "filled" and float(filled_qty) > 0:
            print("PASS: Alpaca paper account confirmed filled BUY. No automatic SELL attempted.")
            print("IMPORTANT: close the test position manually in the paper account.")
            return 0
        if status in {"canceled", "expired", "rejected"}:
            print("FAIL: paper order terminal without fill.")
            return 1
        time.sleep(2)
    print("INCONCLUSIVE: order may remain open or partially filled. Check paper account manually; do not repeat blindly.")
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
