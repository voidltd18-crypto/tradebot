from __future__ import annotations
from datetime import datetime, UTC
from typing import Dict, Any
from .base import BaseEngine
from backend.config import STOCK_UNIVERSE, STOCK_NOTIONAL_USD, STOCK_NO_SAME_DAY_SELLS

class StockEngine(BaseEngine):
    def __init__(self, state, service, strategy, interval=10, dry_run=True):
        super().__init__(state, interval)
        self.service = service
        self.strategy = strategy
        self.dry_run = dry_run
        self.price_ref: Dict[str, float] = {}
        self.highest: Dict[str, float] = {}
        self.bought_day: Dict[str, str] = {}
        self.state.config.update({'universe': STOCK_UNIVERSE, 'notionalUsd': STOCK_NOTIONAL_USD, 'noSameDaySells': STOCK_NO_SAME_DAY_SELLS})

    def tick(self):
        if not self.service.market_open():
            self.state.log('market closed')
            return
        positions = self.service.positions()
        held = {p['symbol']: p for p in positions}
        self.state.positions = positions

        # exits first
        today = datetime.now(UTC).strftime('%Y-%m-%d')
        for p in positions:
            sym = p['symbol']
            price = float(p['price'])
            self.highest[sym] = max(float(self.highest.get(sym) or price), price)
            p['highest'] = self.highest[sym]
            if STOCK_NO_SAME_DAY_SELLS and self.bought_day.get(sym) == today:
                self.state.log(f'PDT SAFE HOLD {sym} bought today')
                continue
            action, reason = self.strategy.exit_decision(p)
            if action == 'SELL' and not self.service.has_open_order(sym):
                self.service.sell_qty(sym, float(p['qty']), dry_run=self.dry_run)
                self.state.trades.append({'time': datetime.now(UTC).isoformat(), 'engine': 'stocks', 'side': 'SELL', 'symbol': sym, 'qty': p['qty'], 'reason': reason, 'dryRun': self.dry_run})
                self.state.log(f'SELL {sym} | {reason}')

        scans = []
        for sym in STOCK_UNIVERSE:
            try:
                q = self.service.quote(sym)
                price = q['price']
                ref = self.price_ref.get(sym, price)
                if price > ref:
                    ref = price
                    self.price_ref[sym] = ref
                pullback = ((ref - price) / ref) * 100 if ref else 0
                scan = {'symbol': sym, 'price': price, 'spreadPct': q['spreadPct'], 'pullbackPct': pullback, 'momentumPct': 0.0, 'held': sym in held, 'maxSpreadPct': 0.40, 'minConfidence': 0.55}
                scan['confidence'] = self.strategy.confidence(scan['spreadPct'], scan['pullbackPct'], scan['momentumPct'])
                ok, reason = self.strategy.should_buy(scan)
                scan['readyToBuy'] = ok
                scan['reason'] = reason
                scans.append(scan)
            except Exception as e:
                scans.append({'symbol': sym, 'error': str(e)})
        self.state.scans = scans

        for scan in scans:
            if scan.get('readyToBuy') and scan['symbol'] not in held and not self.service.has_open_order(scan['symbol']):
                self.service.buy_notional(scan['symbol'], STOCK_NOTIONAL_USD, dry_run=self.dry_run)
                self.bought_day[scan['symbol']] = today
                self.highest[scan['symbol']] = scan['price']
                self.state.trades.append({'time': datetime.now(UTC).isoformat(), 'engine': 'stocks', 'side': 'BUY', 'symbol': scan['symbol'], 'notional': STOCK_NOTIONAL_USD, 'reason': scan['reason'], 'dryRun': self.dry_run})
                self.state.log(f'BUY {scan["symbol"]} ${STOCK_NOTIONAL_USD:.2f} | conf={scan["confidence"]:.2f}')
                break
        self.state.updated_at = datetime.now(UTC).isoformat()
