from __future__ import annotations
from typing import Dict, Any, Tuple

class SniperStrategy:
    def __init__(self, fast_stop_loss_pct=-1.0, trail_start_pct=1.2, trail_giveback_pct=0.7):
        self.fast_stop_loss_pct = float(fast_stop_loss_pct)
        self.trail_start_pct = float(trail_start_pct)
        self.trail_giveback_pct = float(trail_giveback_pct)

    def confidence(self, spread_pct: float, pullback_pct: float, momentum_pct: float) -> float:
        score = 0.0
        score += max(0.0, min(0.35, pullback_pct / 4.0))
        score += 0.25 if spread_pct <= 0.15 else 0.15 if spread_pct <= 0.40 else 0.0
        score += 0.25 if momentum_pct >= 0 else 0.10 if momentum_pct >= -0.25 else 0.0
        score += 0.15 if 0.10 <= pullback_pct <= 3.5 else 0.0
        return round(max(0.0, min(1.0, score)), 4)

    def should_buy(self, scan: Dict[str, Any]) -> Tuple[bool, str]:
        if scan.get('held'):
            return False, 'already holding'
        if scan.get('spreadPct', 999) > scan.get('maxSpreadPct', 0.60):
            return False, 'spread too wide'
        if scan.get('pullbackPct', 0) < 0.10:
            return False, 'not enough pullback'
        if scan.get('momentumPct', 0) < -0.25:
            return False, 'momentum too weak'
        if scan.get('confidence', 0) < scan.get('minConfidence', 0.55):
            return False, 'confidence too low'
        return True, 'sniper buy pass'

    def exit_decision(self, position: Dict[str, Any]) -> Tuple[str, str]:
        pnl_pct = float(position.get('pnlPct') or 0.0)
        price = float(position.get('price') or 0.0)
        entry = float(position.get('entry') or 0.0)
        highest = float(position.get('highest') or price)
        if pnl_pct <= self.fast_stop_loss_pct:
            return 'SELL', f'hard stop {pnl_pct:.2f}%'
        if entry > 0 and price > 0:
            trail_start_price = entry * (1 + self.trail_start_pct / 100)
            trail_floor = highest * (1 - self.trail_giveback_pct / 100)
            if price >= trail_start_price and price <= trail_floor:
                return 'SELL', f'trailing stop floor hit {pnl_pct:.2f}%'
        return 'HOLD', 'no exit'
