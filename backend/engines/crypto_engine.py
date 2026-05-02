import os
import time
import threading
from typing import Dict, Any, List
from backend.services.kraken_service import KrakenService
from backend.strategies.sniper_strategy import StrategyConfig, should_buy, exit_reason

class CryptoEngine:
    def __init__(self):
        pairs = os.getenv("CRYPTO_PAIRS", "BTC/USDT,ETH/USDT,SOL/USDT,XRP/USDT,ADA/USDT,LINK/USDT,DOGE/USDT,LTC/USDT")
        self.pairs = [p.strip().upper() for p in pairs.split(",") if p.strip()]
        self.service = KrakenService()
        self.cfg = StrategyConfig()
        self.interval = int(os.getenv("CRYPTO_CHECK_INTERVAL", "15"))
        self.position_usdt = float(os.getenv("CRYPTO_POSITION_USDT", "25"))
        self.max_positions = int(os.getenv("CRYPTO_MAX_POSITIONS", "4"))
        self.running = False
        self.thread = None
        self.logs: List[str] = []
        self.scans: List[Dict[str, Any]] = []
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.state: Dict[str, Dict[str, Any]] = {p: {"ref": None, "curve": []} for p in self.pairs}

    def log(self, msg: str):
        line = time.strftime("%H:%M:%S") + " | " + msg
        print(line)
        self.logs.append(line)
        self.logs = self.logs[-200:]

    def start(self):
        if self.running:
            return {"ok": True, "message": "Crypto engine already running"}
        self.running = True
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()
        return {"ok": True, "message": "Crypto engine started"}

    def stop(self):
        self.running = False
        return {"ok": True, "message": "Crypto engine stopping"}

    def compute_scan(self, pair: str):
        q = self.service.ticker(pair)
        price = q["price"]
        st = self.state.setdefault(pair, {"ref": None, "curve": []})
        if st["ref"] is None or price > st["ref"]:
            st["ref"] = price
        ref = st["ref"] or price
        curve = st["curve"]
        curve.append(price)
        if len(curve) > 100:
            curve.pop(0)
        old = curve[-5] if len(curve) >= 5 else price
        momentum = (price / old - 1) if old else 0.0
        pullback = max(0.0, (ref - price) / ref) if ref else 0.0
        quality = 0.0
        if self.cfg.min_pullback <= pullback <= self.cfg.max_pullback:
            quality += pullback * 4.0
        if q["spread"] <= self.cfg.max_spread:
            quality += max(0, self.cfg.prefer_spread_under - q["spread"]) * 3.0
        if momentum >= 0:
            quality += momentum * 0.8
        ready = price <= ref * 0.999 and len(curve) >= 5 and momentum >= self.cfg.min_momentum
        scan = {**q, "ref": ref, "pullback": pullback, "momentum": momentum, "quality": quality, "ready": ready}
        ok, reason = should_buy(scan, self.cfg)
        scan["buyPass"] = ok
        scan["reason"] = reason
        return scan

    def manage_positions(self):
        for pair, pos in list(self.positions.items()):
            q = self.service.ticker(pair)
            price = q["price"]
            pos["price"] = price
            pos["highest"] = max(float(pos.get("highest", price)), price)
            pos["pnlPct"] = ((price / pos["entry"]) - 1) * 100 if pos["entry"] else 0.0
            do_exit, reason = exit_reason(pos, self.cfg)
            if do_exit:
                try:
                    self.service.market_sell_amount(pair, pos["amount"])
                    self.log(f"SELL {pair} | {reason} | pnl={pos['pnlPct']:.2f}%")
                    del self.positions[pair]
                except Exception as e:
                    self.log(f"SELL ERROR {pair}: {e}")

    def maybe_buy(self):
        if len(self.positions) >= self.max_positions:
            return
        candidates = [s for s in self.scans if s.get("buyPass") and s["symbol"] not in self.positions]
        candidates.sort(key=lambda s: (-s.get("confidence", 0), -s.get("quality", 0), s.get("spread", 1)))
        if not candidates:
            return
        c = candidates[0]
        pair = c["symbol"]
        price = c["price"]
        amount = self.position_usdt / price
        try:
            self.service.market_buy_usdt(pair, self.position_usdt)
            self.positions[pair] = {"symbol": pair, "entry": price, "price": price, "highest": price, "amount": amount, "valueUSDT": self.position_usdt, "pnlPct": 0.0}
            self.log(f"BUY {pair} | ${self.position_usdt:.2f} | confidence={c.get('confidence', 0):.2f}")
        except Exception as e:
            self.log(f"BUY ERROR {pair}: {e}")

    def loop(self):
        self.log("Kraken crypto engine loop started")
        while self.running:
            try:
                scans = []
                for pair in self.pairs:
                    try:
                        scan = self.compute_scan(pair)
                        scans.append(scan)
                        self.log(f"SCAN {pair} | price={scan['price']:.4f} | conf={scan.get('confidence',0):.2f} | pass={scan['buyPass']}")
                    except Exception as e:
                        self.log(f"SCAN ERROR {pair}: {e}")
                self.scans = scans
                self.manage_positions()
                self.maybe_buy()
            except Exception as e:
                self.log(f"CRYPTO LOOP ERROR: {e}")
            time.sleep(self.interval)
        self.log("Kraken crypto engine loop stopped")

    def status(self):
        return {
            "running": self.running,
            "exchange": "kraken",
            "dryRun": self.service.dry_run,
            "pairs": self.pairs,
            "positions": list(self.positions.values()),
            "scans": self.scans,
            "logs": self.logs[-80:],
            "config": {"interval": self.interval, "positionUSDT": self.position_usdt, "maxPositions": self.max_positions, "fastStopLossPct": self.cfg.fast_stop_loss_pct},
        }
