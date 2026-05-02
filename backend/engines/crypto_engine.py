from __future__ import annotations
from datetime import datetime, UTC
from typing import Dict, Any
from .base import BaseEngine
from backend.config import CRYPTO_UNIVERSE, CRYPTO_NOTIONAL_USDT

class CryptoEngine(BaseEngine):
    def __init__(self, state, service, strategy, interval=10, dry_run=True):
        super().__init__(state, interval)
        self.service = service
        self.strategy = strategy
        self.dry_run = dry_run
        self.price_ref: Dict[str, float] = {}
        self.virtual_positions: Dict[str, Dict[str, Any]] = {}  # used for dry-run/testnet visibility
        self.state.config.update({'universe': CRYPTO_UNIVERSE, 'notionalUsdt': CRYPTO_NOTIONAL_USDT, 'market': '24/7'})

    def _positions(self):
        if self.dry_run:
            out = []
            for sym, p in list(self.virtual_positions.items()):
                price = self.service.quote(sym)['price']
                p['price'] = price
                p['pnlPct'] = ((price / p['entry']) - 1) * 100 if p['entry'] else 0
                p['highest'] = max(float(p.get('highest') or price), price)
                out.append(dict(p))
            return out
        return self.service.positions_from_balances(CRYPTO_UNIVERSE)

    def tick(self):
        positions = self._positions()
        held = {p['symbol']: p for p in positions}
        self.state.positions = positions

        for p in positions:
            action, reason = self.strategy.exit_decision(p)
            if action == 'SELL':
                self.service.sell_qty(p['symbol'], float(p['qty']), dry_run=self.dry_run)
                self.virtual_positions.pop(p['symbol'], None)
                self.state.trades.append({'time': datetime.now(UTC).isoformat(), 'engine': 'crypto', 'side': 'SELL', 'symbol': p['symbol'], 'qty': p['qty'], 'reason': reason, 'dryRun': self.dry_run})
                self.state.log(f'SELL {p["symbol"]} | {reason}')

        scans = []
        for sym in CRYPTO_UNIVERSE:
            try:
                q = self.service.quote(sym)
                price = q['price']
                ref = self.price_ref.get(sym, price)
                if price > ref:
                    ref = price
                    self.price_ref[sym] = ref
                pullback = ((ref - price) / ref) * 100 if ref else 0
                scan = {'symbol': sym, 'price': price, 'spreadPct': q['spreadPct'], 'pullbackPct': pullback, 'momentumPct': 0.0, 'held': sym in held, 'maxSpreadPct': 0.20, 'minConfidence': 0.55}
                scan['confidence'] = self.strategy.confidence(scan['spreadPct'], scan['pullbackPct'], scan['momentumPct'])
                ok, reason = self.strategy.should_buy(scan)
                scan['readyToBuy'] = ok
                scan['reason'] = reason
                scans.append(scan)
            except Exception as e:
                scans.append({'symbol': sym, 'error': str(e)})
        self.state.scans = scans

        for scan in scans:
            if scan.get('readyToBuy') and scan['symbol'] not in held:
                order = self.service.buy_notional(scan['symbol'], CRYPTO_NOTIONAL_USDT, dry_run=self.dry_run)
                qty = float(order.get('amount') or (CRYPTO_NOTIONAL_USDT / scan['price'])) if isinstance(order, dict) else CRYPTO_NOTIONAL_USDT / scan['price']
                if self.dry_run:
                    self.virtual_positions[scan['symbol']] = {'symbol': scan['symbol'], 'qty': qty, 'entry': scan['price'], 'price': scan['price'], 'highest': scan['price'], 'pnlPct': 0.0, 'marketValue': CRYPTO_NOTIONAL_USDT}
                self.state.trades.append({'time': datetime.now(UTC).isoformat(), 'engine': 'crypto', 'side': 'BUY', 'symbol': scan['symbol'], 'notional': CRYPTO_NOTIONAL_USDT, 'reason': scan['reason'], 'dryRun': self.dry_run})
                self.state.log(f'BUY {scan["symbol"]} ${CRYPTO_NOTIONAL_USDT:.2f} | conf={scan["confidence"]:.2f}')
                break
        self.state.updated_at = datetime.now(UTC).isoformat()
