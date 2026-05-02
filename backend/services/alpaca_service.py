from __future__ import annotations
from typing import Dict, Any, List
from datetime import datetime, UTC

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
    from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestQuoteRequest
except Exception:  # allows crypto-only deploys
    TradingClient = None

class AlpacaService:
    def __init__(self, api_key: str, api_secret: str, paper: bool = True):
        if not TradingClient:
            raise RuntimeError('alpaca-py is not installed')
        if not api_key or not api_secret:
            raise RuntimeError('Missing Alpaca API keys')
        self.trading = TradingClient(api_key, api_secret, paper=paper)
        self.data = StockHistoricalDataClient(api_key, api_secret)

    def market_open(self) -> bool:
        return bool(self.trading.get_clock().is_open)

    def account(self) -> Dict[str, Any]:
        a = self.trading.get_account()
        return {'equity': float(a.equity), 'buyingPower': float(a.buying_power), 'cash': float(a.cash)}

    def quote(self, symbol: str) -> Dict[str, float]:
        q = self.data.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=symbol))[symbol]
        bid = float(q.bid_price or 0)
        ask = float(q.ask_price or 0)
        if bid <= 0 or ask <= 0:
            raise ValueError(f'Bad quote for {symbol}')
        mid = (bid + ask) / 2
        return {'bid': bid, 'ask': ask, 'price': mid, 'spreadPct': ((ask - bid) / mid) * 100}

    def positions(self) -> List[Dict[str, Any]]:
        out = []
        for p in self.trading.get_all_positions():
            qty = float(p.qty)
            entry = float(p.avg_entry_price)
            price = float(getattr(p, 'current_price', 0) or 0)
            if price <= 0:
                try:
                    price = self.quote(str(p.symbol))['price']
                except Exception:
                    price = entry
            pnl_pct = ((price / entry) - 1) * 100 if entry > 0 else 0
            out.append({'symbol': str(p.symbol).upper(), 'qty': qty, 'entry': entry, 'price': price, 'pnlPct': pnl_pct, 'marketValue': float(p.market_value)})
        return out

    def has_open_order(self, symbol: str) -> bool:
        try:
            orders = self.trading.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))
            return any(str(o.symbol).upper() == symbol.upper() for o in orders)
        except Exception:
            return False

    def buy_notional(self, symbol: str, notional: float, dry_run: bool = True):
        if dry_run:
            return {'dryRun': True, 'side': 'BUY', 'symbol': symbol, 'notional': notional}
        req = MarketOrderRequest(symbol=symbol, notional=round(notional, 2), side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
        return self.trading.submit_order(req)

    def sell_qty(self, symbol: str, qty: float, dry_run: bool = True):
        if dry_run:
            return {'dryRun': True, 'side': 'SELL', 'symbol': symbol, 'qty': qty}
        req = MarketOrderRequest(symbol=symbol, qty=round(qty, 6), side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
        return self.trading.submit_order(req)
