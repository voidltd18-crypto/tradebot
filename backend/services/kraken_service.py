import os
import time
from typing import Dict, Any, List
import ccxt

class KrakenService:
    def __init__(self):
        self.api_key = os.getenv("KRAKEN_API_KEY", "")
        self.secret = os.getenv("KRAKEN_SECRET_KEY", "")
        self.dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
        self.exchange = ccxt.kraken({
            "apiKey": self.api_key,
            "secret": self.secret,
            "enableRateLimit": True,
        })
        self.markets_loaded = False

    def load(self):
        if not self.markets_loaded:
            self.exchange.load_markets()
            self.markets_loaded = True

    def ticker(self, symbol: str) -> Dict[str, Any]:
        self.load()
        t = self.exchange.fetch_ticker(symbol)
        bid = float(t.get("bid") or 0)
        ask = float(t.get("ask") or 0)
        last = float(t.get("last") or 0)
        price = (bid + ask) / 2 if bid > 0 and ask > 0 else last
        spread = ((ask - bid) / price) if price and bid and ask else 0.0
        return {"symbol": symbol, "price": price, "bid": bid, "ask": ask, "spread": spread, "timestamp": t.get("timestamp")}

    def balance(self):
        if self.dry_run or not self.api_key or not self.secret:
            return {"USDT": {"free": 1000.0, "total": 1000.0}, "dryRun": True}
        self.load()
        return self.exchange.fetch_balance()

    def market_buy_usdt(self, symbol: str, usdt_amount: float):
        self.load()
        if self.dry_run:
            return {"dryRun": True, "side": "buy", "symbol": symbol, "cost": usdt_amount, "id": f"dry-buy-{int(time.time())}"}
        ticker = self.ticker(symbol)
        price = ticker["price"]
        amount = float(usdt_amount) / price
        return self.exchange.create_market_buy_order(symbol, amount)

    def market_sell_amount(self, symbol: str, amount: float):
        self.load()
        if self.dry_run:
            return {"dryRun": True, "side": "sell", "symbol": symbol, "amount": amount, "id": f"dry-sell-{int(time.time())}"}
        return self.exchange.create_market_sell_order(symbol, amount)
