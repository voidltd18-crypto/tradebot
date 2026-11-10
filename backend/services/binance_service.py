from __future__ import annotations
from typing import Dict, Any, List

try:
    import ccxt
except Exception:
    ccxt = None

class BinanceService:
    def __init__(self, api_key: str, secret: str, testnet: bool = True):
        if not ccxt:
            raise RuntimeError('ccxt is not installed')
        self.exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'},
        })
        if testnet:
            self.exchange.set_sandbox_mode(True)
        self.markets = None

    def load_markets(self):
        if self.markets is None:
            self.markets = self.exchange.load_markets()
        return self.markets

    def quote(self, symbol: str) -> Dict[str, float]:
        ticker = self.exchange.fetch_ticker(symbol)
        bid = float(ticker.get('bid') or 0)
        ask = float(ticker.get('ask') or 0)
        last = float(ticker.get('last') or ticker.get('close') or 0)
        price = (bid + ask) / 2 if bid > 0 and ask > 0 else last
        if price <= 0:
            raise ValueError(f'Bad ticker for {symbol}')
        spread = ((ask - bid) / price) * 100 if bid > 0 and ask > 0 else 0.0
        return {'bid': bid, 'ask': ask, 'price': price, 'spreadPct': spread}

    def balances(self):
        return self.exchange.fetch_balance()

    def positions_from_balances(self, universe: List[str]) -> List[Dict[str, Any]]:
        bal = self.balances()
        out = []
        for symbol in universe:
            base = symbol.split('/')[0]
            qty = float((bal.get('total') or {}).get(base) or 0)
            if qty <= 0:
                continue
            price = self.quote(symbol)['price']
            out.append({'symbol': symbol, 'base': base, 'qty': qty, 'entry': 0.0, 'price': price, 'pnlPct': 0.0, 'marketValue': qty * price})
        return out

    def buy_notional(self, symbol: str, notional: float, dry_run: bool = True):
        quote = self.quote(symbol)
        amount = notional / quote['price']
        if dry_run:
            return {'dryRun': True, 'side': 'BUY', 'symbol': symbol, 'notional': notional, 'amount': amount}
        return self.exchange.create_market_buy_order(symbol, amount)

    def sell_qty(self, symbol: str, qty: float, dry_run: bool = True):
        if dry_run:
            return {'dryRun': True, 'side': 'SELL', 'symbol': symbol, 'qty': qty}
        return self.exchange.create_market_sell_order(symbol, qty)
