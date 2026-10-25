"""Isolated Alpaca PAPER account Buy Again smoke test.

Dry-run by default. NEVER reads TRADEBOT / ALPACA live credentials and NEVER
uses the live TradeBot client. Requires separate paper credentials.
Usage:
  PAPER_ALPACA_API_KEY=... PAPER_ALPACA_SECRET_KEY=... python scripts/check_crypto_rebuy_paper.py
  PAPER_ALPACA_API_KEY=... PAPER_ALPACA_SECRET_KEY=... python scripts/check_crypto_rebuy_paper.py --submit
"""
import argparse
import os
import sys
import uuid
from decimal import Decimal


def main(argv=None):
    parser = argparse.ArgumentParser(description="Alpaca paper-only crypto re-buy test")
    parser.add_argument("--submit", action="store_true", help="Send ONE $2 paper buy; dry-run otherwise")
    parser.add_argument("--symbol", choices=["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD"], default="XRP/USD")
    args = parser.parse_args(argv)

    key = os.environ.get("PAPER_ALPACA_API_KEY", "").strip()
    secret = os.environ.get("PAPER_ALPACA_SECRET_KEY", "").strip()
    if not key or not secret:
        print("STOP: Set separate PAPER_ALPACA_API_KEY and PAPER_ALPACA_SECRET_KEY; never use live keys.")
        return 2

    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    client = TradingClient(key, secret, paper=True)  # Hard-coded paper endpoint.
    try:
        account = client.get_account()
        asset = client.get_asset(args.symbol.replace("/", ""))
        available = Decimal(str(getattr(account, "non_marginable_buying_power", 0)))
        print("Paper broker authentication: OK")
        print("Coin:", args.symbol, "tradable:", bool(getattr(asset, "tradable", False)))
        print("Paper buying power sufficient for $2:", available >= Decimal("2"))
        if not getattr(asset, "tradable", False) or "crypto" not in str(getattr(asset, "asset_class", "")).lower():
            print("STOP: paper broker did not verify crypto tradability")
            return 3
        if available < Decimal("2"):
            print("STOP: insufficient PAPER buying power")
            return 3
        if not args.submit:
            print("DRY RUN ONLY: no order placed. Add --submit for exactly one $2 PAPER order.")
            return 0
        # Single deliberate PAPER order. No automatic retries.
        order_id = "tb-paper-smoke-" + uuid.uuid4().hex[:20]
        order = client.submit_order(MarketOrderRequest(
            symbol=args.symbol, notional=2.0, side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC, client_order_id=order_id,
        ))
        print("PAPER order submitted:", str(order.id))
        try:
            verified = client.get_order_by_id(order.id)
            print("PAPER broker order status:", str(verified.status))
            print("PAPER filled qty:", str(getattr(verified, "filled_qty", "0")))
        except Exception:
            print("PAPER order accepted but fill lookup unavailable; inspect paper orders before any retry")
        print("Paper test complete. No live TradeBot settings or positions changed.")
        return 0
    except Exception as exc:
        print("PAPER API error:", type(exc).__name__, "— verify paper credentials / Alpaca order history.")
        return 4


if __name__ == "__main__":
    sys.exit(main())
