from dataclasses import dataclass
from typing import Dict, Any, Tuple

@dataclass
class StrategyConfig:
    max_spread: float = 0.006
    prefer_spread_under: float = 0.0025
    min_pullback: float = 0.001
    max_pullback: float = 0.035
    min_momentum: float = -0.004
    min_confidence: float = 0.58
    min_quality: float = 0.012
    fast_stop_loss_pct: float = -1.0
    trail_start_pct: float = 1.2
    trail_giveback_pct: float = 0.7


def confidence(scan: Dict[str, Any], cfg: StrategyConfig) -> Tuple[float, str]:
    spread = float(scan.get("spread", 1.0))
    pullback = float(scan.get("pullback", 0.0))
    momentum = float(scan.get("momentum", 0.0))
    quality = float(scan.get("quality", 0.0))
    c = 0.0
    c += min(0.35, quality * 10.0)
    c += 0.25 if spread <= cfg.prefer_spread_under else 0.12 if spread <= cfg.max_spread else 0.0
    c += 0.20 if momentum >= 0 else 0.08 if momentum >= cfg.min_momentum else 0.0
    c += 0.20 if cfg.min_pullback <= pullback <= cfg.max_pullback else 0.0
    c = max(0.0, min(1.0, c))
    label = "HIGH" if c >= 0.75 else "MEDIUM" if c >= cfg.min_confidence else "LOW"
    return c, label


def should_buy(scan: Dict[str, Any], cfg: StrategyConfig):
    c, label = confidence(scan, cfg)
    scan["confidence"] = c
    scan["confidenceLabel"] = label
    if c < cfg.min_confidence:
        return False, f"confidence too low {c:.2f}"
    if float(scan.get("quality", 0.0)) < cfg.min_quality:
        return False, "quality too low"
    if float(scan.get("spread", 1.0)) > cfg.max_spread:
        return False, "spread too wide"
    if not (cfg.min_pullback <= float(scan.get("pullback", 0.0)) <= cfg.max_pullback):
        return False, "pullback outside range"
    if float(scan.get("momentum", 0.0)) < cfg.min_momentum:
        return False, "momentum too weak"
    return bool(scan.get("ready", False)), "buy ready" if scan.get("ready", False) else "not ready"


def exit_reason(position: Dict[str, Any], cfg: StrategyConfig):
    pnl_pct = float(position.get("pnlPct", 0.0))
    if pnl_pct <= cfg.fast_stop_loss_pct:
        return True, "HARD FAST STOP LOSS"
    price = float(position.get("price", 0.0))
    entry = float(position.get("entry", 0.0))
    highest = float(position.get("highest", price))
    if entry > 0 and price >= entry * (1 + cfg.trail_start_pct / 100):
        floor = highest * (1 - cfg.trail_giveback_pct / 100)
        if price <= floor:
            return True, "TRAILING PROFIT"
    return False, "HOLD"
