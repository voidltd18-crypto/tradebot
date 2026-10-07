"""V18.3.54 Historical Evidence Accelerator.

Shadow-research only. Uses the large persisted Shadow ledger to stop spending
research slots on historically weak exploratory cohorts. Qualified/live trading
permission remains under the existing Governor and is not loosened here.
"""

from __future__ import annotations
import time
import threading
from typing import Any, Dict, List

_CACHE: Dict[str, Any] = {"at": 0.0, "model": None}
_RUNTIME: Dict[str, Any] = {
    "installed": False,
    "checks": 0,
    "exploreAllowed": 0,
    "exploreBlockedWeakRegime": 0,
    "exploreBlockedMomentum": 0,
    "exploreBlockedHistorical": 0,
    "lastDecision": None,
}
_LOCK = threading.RLock()


def install_v18354_historical_evidence_accelerator(app, m):
    original = getattr(m, "_v18315_entry_allowed", None)
    if not callable(original):
        print("V18.3.54 EVIDENCE ACCELERATOR | skipped: base gate missing", flush=True)
        return

    def score_bin(score: float) -> str:
        fn = getattr(m, "_v18315_score_bin", None)
        if callable(fn):
            try:
                return str(fn(float(score)))
            except Exception:
                pass
        lo = int(float(score) * 20) / 20.0
        return f"{lo:.2f}-{lo+0.05:.2f}"

    def stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        n = len(rows)
        pnl = sum(float(x.get("pnlUsd") or 0.0) for x in rows)
        wins = sum(1 for x in rows if float(x.get("pnlUsd") or 0.0) > 0)
        losses = [abs(float(x.get("pnlUsd") or 0.0)) for x in rows if float(x.get("pnlUsd") or 0.0) < 0]
        winners = [float(x.get("pnlUsd") or 0.0) for x in rows if float(x.get("pnlUsd") or 0.0) > 0]
        return {
            "trades": n,
            "pnlUsd": round(pnl, 4),
            "expectancyUsd": round(pnl / n, 5) if n else 0.0,
            "winRatePct": round((wins / n) * 100.0, 2) if n else 0.0,
            "avgWinnerUsd": round(sum(winners) / len(winners), 5) if winners else 0.0,
            "avgLoserUsd": round(-(sum(losses) / len(losses)), 5) if losses else 0.0,
        }

    def build_model(force: bool = False) -> Dict[str, Any]:
        now = time.time()
        with _LOCK:
            if not force and _CACHE.get("model") is not None and now - float(_CACHE.get("at") or 0.0) < 300:
                return dict(_CACHE["model"])

        conn = m.db_connect()
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT id,timestamp,symbol,side,score,pnl_usd,pnl_pct,reason "
                "FROM v18232_crypto_trades ORDER BY id ASC"
            ).fetchall()]
        finally:
            conn.close()

        open_buy: Dict[str, Dict[str, Any]] = {}
        paired: List[Dict[str, Any]] = []
        for r in rows:
            sym = str(r.get("symbol") or "").upper().strip()
            if not sym:
                continue
            side = str(r.get("side") or "").upper()
            if side == "BUY":
                open_buy[sym] = r
                continue
            if side != "SELL":
                continue
            b = open_buy.pop(sym, None)
            if not b:
                continue
            try:
                score = float(b.get("score") or r.get("score") or 0.0)
                pnl = float(r.get("pnl_usd") or 0.0)
                pct = float(r.get("pnl_pct") or 0.0)
            except Exception:
                continue
            entry_reason = str(b.get("reason") or "")
            paired.append({
                "symbol": sym,
                "score": score,
                "scoreBin": score_bin(score),
                "pnlUsd": pnl,
                "pnlPct": pct,
                "entryReason": entry_reason,
                "exploratory": "RESEARCH EXPLORE" in entry_reason.upper(),
                "exitReason": str(r.get("reason") or ""),
            })

        bins: Dict[str, List[Dict[str, Any]]] = {}
        syms: Dict[str, List[Dict[str, Any]]] = {}
        for x in paired:
            bins.setdefault(x["scoreBin"], []).append(x)
            syms.setdefault(x["symbol"], []).append(x)

        bin_stats = {k: stats(v) for k, v in bins.items()}
        sym_stats = {k: stats(v) for k, v in syms.items()}

        # Deliberately conservative: history is used to focus Shadow exploration,
        # not to grant LIVE permission.
        positive_bins = sorted([
            k for k, v in bin_stats.items()
            if int(v["trades"]) >= 40 and float(v["expectancyUsd"]) > 0 and float(v["pnlUsd"]) > 0
        ])
        positive_symbols = sorted([
            k for k, v in sym_stats.items()
            if int(v["trades"]) >= 20 and float(v["expectancyUsd"]) > 0 and float(v["pnlUsd"]) > 0
        ])
        negative_symbols = sorted([
            k for k, v in sym_stats.items()
            if int(v["trades"]) >= 20 and float(v["expectancyUsd"]) < 0 and float(v["pnlUsd"]) < 0
        ])

        model = {
            "version": "V18.3.54",
            "outcomes": len(paired),
            "overall": stats(paired),
            "positiveScoreBins": positive_bins,
            "positiveSymbols": positive_symbols,
            "negativeSymbols": negative_symbols,
            "scoreBins": bin_stats,
            "symbolStats": sym_stats,
            "limitations": [
                "Historical Shadow ledger stores entry score/symbol/outcome but not entry-time regime or 15m/60m momentum.",
                "Momentum/regime checks therefore use the current scan only.",
            ],
        }
        with _LOCK:
            _CACHE.update({"at": now, "model": model})
        return dict(model)

    def accelerated_gate(scan: Dict[str, Any], research_explore: bool = False) -> bool:
        # Never change the established qualified/live evidence gate.
        if not research_explore:
            return bool(original(scan, research_explore=False))

        with _LOCK:
            _RUNTIME["checks"] += 1

        # Keep the base safety contract first.
        if not bool(original(scan, research_explore=True)):
            return False

        regime_obj = getattr(m, "_v18273_last_regime", {}) or {}
        regime = str(regime_obj.get("name") or scan.get("marketRegime") or "mixed").lower()
        ret15 = float(scan.get("return15mPct") or 0.0)
        ret60 = float(scan.get("return60mPct") or 0.0)
        symbol = str(scan.get("symbol") or "").upper().strip()
        band = score_bin(float(scan.get("score") or 0.0))

        if regime == "weak":
            with _LOCK:
                _RUNTIME["exploreBlockedWeakRegime"] += 1
                _RUNTIME["lastDecision"] = {"symbol": symbol, "allowed": False, "reason": "WEAK_REGIME"}
            return False

        # Mixed markets must be positively moving on both windows. Strong markets
        # may have a flat 15m bar, but 60m still has to be positive.
        momentum_ok = (ret15 > 0 and ret60 > 0) if regime == "mixed" else (ret15 >= 0 and ret60 > 0)
        if not momentum_ok:
            with _LOCK:
                _RUNTIME["exploreBlockedMomentum"] += 1
                _RUNTIME["lastDecision"] = {"symbol": symbol, "allowed": False, "reason": "MOMENTUM"}
            return False

        model = build_model()
        outcomes = int(model.get("outcomes") or 0)
        if outcomes >= 200:
            positives = set(model.get("positiveSymbols") or [])
            good_bins = set(model.get("positiveScoreBins") or [])
            negatives = set(model.get("negativeSymbols") or [])
            if symbol in negatives or (symbol not in positives and band not in good_bins):
                with _LOCK:
                    _RUNTIME["exploreBlockedHistorical"] += 1
                    _RUNTIME["lastDecision"] = {
                        "symbol": symbol, "allowed": False, "reason": "HISTORICAL_COHORT",
                        "scoreBin": band, "outcomes": outcomes,
                    }
                return False

        with _LOCK:
            _RUNTIME["exploreAllowed"] += 1
            _RUNTIME["lastDecision"] = {
                "symbol": symbol, "allowed": True, "reason": "ACCELERATED_RESEARCH",
                "scoreBin": band, "regime": regime, "ret15": ret15, "ret60": ret60,
            }
        return True

    m._v18315_entry_allowed = accelerated_gate

    @app.get("/v18/crypto-evidence-accelerator")
    def v18354_crypto_evidence_accelerator():
        model = build_model()
        top_positive = sorted(
            [{"symbol": k, **v} for k, v in (model.get("symbolStats") or {}).items() if int(v.get("trades") or 0) >= 10],
            key=lambda x: (float(x.get("expectancyUsd") or 0.0), int(x.get("trades") or 0)),
            reverse=True,
        )[:12]
        top_negative = sorted(
            [{"symbol": k, **v} for k, v in (model.get("symbolStats") or {}).items() if int(v.get("trades") or 0) >= 10],
            key=lambda x: (float(x.get("expectancyUsd") or 0.0), -int(x.get("trades") or 0)),
        )[:12]
        with _LOCK:
            runtime = dict(_RUNTIME)
        return {
            "ok": True,
            "version": "V18.3.54",
            "shadowOnly": True,
            "liveTradingChanged": False,
            "stockTradingChanged": False,
            "model": {
                "outcomes": model.get("outcomes"),
                "overall": model.get("overall"),
                "positiveScoreBins": model.get("positiveScoreBins"),
                "positiveSymbols": model.get("positiveSymbols"),
                "negativeSymbols": model.get("negativeSymbols"),
                "limitations": model.get("limitations"),
            },
            "runtime": runtime,
            "topPositiveSymbols": top_positive,
            "topNegativeSymbols": top_negative,
        }

    with _LOCK:
        _RUNTIME["installed"] = True
    try:
        model = build_model(force=True)
        print(
            "V18.3.54 HISTORICAL EVIDENCE ACCELERATOR | "
            f"outcomes={int(model.get('outcomes') or 0)} "
            f"positive_bins={len(model.get('positiveScoreBins') or [])} "
            f"positive_symbols={len(model.get('positiveSymbols') or [])} "
            f"negative_symbols={len(model.get('negativeSymbols') or [])} "
            "shadow_only=True live_changed=False",
            flush=True,
        )
    except Exception as exc:
        print(f"V18.3.54 HISTORICAL EVIDENCE ACCELERATOR | startup model error={exc}", flush=True)
