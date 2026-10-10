"""V18.3.78 Crypto Evidence Decision Engine.

Advisory/shadow only. Converts the accumulated crypto shadow ledger into a
live-market recommendation layer without submitting orders or changing the
existing live crypto authority.

The engine:
- learns positive/negative symbol cohorts from closed shadow outcomes
- learns positive score bands from the same outcome ledger
- ranks current scanner rows using that historical evidence
- explicitly blocks historically negative cohorts
- reports what the evidence model WOULD select, plus the historical expectancy
  behind each selection

No broker order function is called anywhere in this module.
"""

from __future__ import annotations

from typing import Any, Dict, List
from fastapi import Body

VERSION = "V18.3.78"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except Exception:
        return float(default)


def _score_bin(score: float) -> str:
    lo = int(float(score) * 20) / 20.0
    return f"{lo:.2f}-{lo + 0.05:.2f}"


def _stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    pnl = sum(_num(x.get("pnlUsd")) for x in rows)
    wins = sum(1 for x in rows if _num(x.get("pnlUsd")) > 0)
    return {
        "trades": n,
        "pnlUsd": round(pnl, 4),
        "expectancyUsd": round(pnl / n, 5) if n else 0.0,
        "winRatePct": round((wins / n) * 100.0, 2) if n else 0.0,
    }


def _build_model(m) -> Dict[str, Any]:
    conn = m.db_connect()
    try:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT id,timestamp,symbol,side,score,pnl_usd,pnl_pct,reason "
                "FROM v18232_crypto_trades ORDER BY id ASC"
            ).fetchall()
        ]
    finally:
        conn.close()

    open_buy: Dict[str, Dict[str, Any]] = {}
    paired: List[Dict[str, Any]] = []
    for row in rows:
        symbol = str(row.get("symbol") or "").upper().strip()
        side = str(row.get("side") or "").upper().strip()
        if not symbol:
            continue
        if side == "BUY":
            open_buy[symbol] = row
            continue
        if side != "SELL":
            continue
        buy = open_buy.pop(symbol, None)
        if not buy:
            continue
        score = _num(buy.get("score"), _num(row.get("score")))
        paired.append(
            {
                "symbol": symbol,
                "score": score,
                "scoreBin": _score_bin(score),
                "pnlUsd": _num(row.get("pnl_usd")),
                "pnlPct": _num(row.get("pnl_pct")),
                "entryReason": str(buy.get("reason") or ""),
                "exitReason": str(row.get("reason") or ""),
            }
        )

    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    by_bin: Dict[str, List[Dict[str, Any]]] = {}
    for row in paired:
        by_symbol.setdefault(row["symbol"], []).append(row)
        by_bin.setdefault(row["scoreBin"], []).append(row)

    symbol_stats = {k: _stats(v) for k, v in by_symbol.items()}
    bin_stats = {k: _stats(v) for k, v in by_bin.items()}

    positive_symbols = sorted(
        k
        for k, v in symbol_stats.items()
        if int(v["trades"]) >= 20 and _num(v["expectancyUsd"]) > 0 and _num(v["pnlUsd"]) > 0
    )
    negative_symbols = sorted(
        k
        for k, v in symbol_stats.items()
        if int(v["trades"]) >= 20 and _num(v["expectancyUsd"]) < 0 and _num(v["pnlUsd"]) < 0
    )
    positive_bins = sorted(
        k
        for k, v in bin_stats.items()
        if int(v["trades"]) >= 40 and _num(v["expectancyUsd"]) > 0 and _num(v["pnlUsd"]) > 0
    )

    return {
        "outcomes": len(paired),
        "overall": _stats(paired),
        "positiveSymbols": positive_symbols,
        "negativeSymbols": negative_symbols,
        "positiveScoreBins": positive_bins,
        "symbolStats": symbol_stats,
        "scoreBins": bin_stats,
    }


def install_v18378_crypto_evidence_decision_engine(app, m) -> None:
    @app.post("/v18/crypto-evidence-decisions")
    def v18378_crypto_evidence_decisions(payload: Dict[str, Any] = Body(default={})):
        scans = payload.get("scans") if isinstance(payload, dict) else []
        scans = scans if isinstance(scans, list) else []
        model = _build_model(m)

        positives = set(model.get("positiveSymbols") or [])
        negatives = set(model.get("negativeSymbols") or [])
        positive_bins = set(model.get("positiveScoreBins") or [])
        symbol_stats = model.get("symbolStats") or {}
        bin_stats = model.get("scoreBins") or {}

        decisions: List[Dict[str, Any]] = []
        for scan in scans:
            if not isinstance(scan, dict):
                continue
            symbol = str(scan.get("symbol") or "").upper().strip()
            if not symbol:
                continue

            score = _num(scan.get("score"))
            band = _score_bin(score)
            sym = dict(symbol_stats.get(symbol) or {})
            bstat = dict(bin_stats.get(band) or {})
            backend_qualified = bool(scan.get("qualified"))
            liquid = scan.get("liquid") is not False
            ret15 = _num(scan.get("return15mPct"))
            ret60 = _num(scan.get("return60mPct"))

            positive_symbol = symbol in positives
            positive_band = band in positive_bins
            negative_symbol = symbol in negatives

            if negative_symbol:
                verdict = "BLOCK"
                reason = "HISTORICALLY_NEGATIVE_SYMBOL"
            elif not liquid:
                verdict = "WAIT"
                reason = "THIN_LIQUIDITY"
            elif not backend_qualified:
                verdict = "WAIT"
                reason = "BASE_SCANNER_NOT_QUALIFIED"
            elif positive_symbol and positive_band:
                verdict = "STRONG_WOULD_BUY"
                reason = "POSITIVE_SYMBOL_AND_SCORE_BAND"
            elif positive_symbol or positive_band:
                verdict = "WOULD_BUY"
                reason = "POSITIVE_HISTORICAL_COHORT"
            else:
                verdict = "WAIT"
                reason = "UNPROVEN_HISTORICAL_COHORT"

            expectancy = max(_num(sym.get("expectancyUsd")), _num(bstat.get("expectancyUsd")))
            evidence_trades = max(int(sym.get("trades") or 0), int(bstat.get("trades") or 0))
            evidence_rank = (
                score * 100.0
                + (15.0 if positive_symbol else 0.0)
                + (10.0 if positive_band else 0.0)
                - (100.0 if negative_symbol else 0.0)
                + expectancy * 10.0
                + min(10.0, evidence_trades / 20.0)
            )

            decisions.append(
                {
                    "symbol": symbol,
                    "verdict": verdict,
                    "reason": reason,
                    "score": round(score, 4),
                    "scoreBin": band,
                    "return15mPct": round(ret15, 4),
                    "return60mPct": round(ret60, 4),
                    "backendQualified": backend_qualified,
                    "liquid": liquid,
                    "positiveSymbol": positive_symbol,
                    "positiveScoreBand": positive_band,
                    "negativeSymbol": negative_symbol,
                    "symbolHistory": sym,
                    "scoreBandHistory": bstat,
                    "historicalExpectancyUsd": round(expectancy, 5),
                    "evidenceTrades": evidence_trades,
                    "evidenceRank": round(evidence_rank, 4),
                }
            )

        decisions.sort(key=lambda x: _num(x.get("evidenceRank")), reverse=True)
        selected = [
            row
            for row in decisions
            if row.get("verdict") in ("STRONG_WOULD_BUY", "WOULD_BUY")
        ]

        return {
            "ok": True,
            "version": VERSION,
            "mode": "SHADOW_EVIDENCE_DECISION_ENGINE",
            "liveAuthority": False,
            "ordersSubmitted": False,
            "description": "Uses accumulated shadow outcomes to rank current crypto opportunities.",
            "model": {
                "outcomes": model.get("outcomes"),
                "overall": model.get("overall"),
                "positiveSymbols": model.get("positiveSymbols"),
                "negativeSymbols": model.get("negativeSymbols"),
                "positiveScoreBins": model.get("positiveScoreBins"),
            },
            "wouldSelect": selected[:10],
            "decisions": decisions,
        }

    print(
        f"{VERSION} CRYPTO EVIDENCE DECISION ENGINE | installed "
        "mode=SHADOW live_authority=False orders=False "
        "historical_symbols=ON score_bands=ON current_scanner=ON",
        flush=True,
    )
