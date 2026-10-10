"""V18.3.79 Confirmed Crypto Buy.

Adds a USER-INITIATED, one-click buy endpoint for V18.3.78 evidence decisions.

Important:
- Never buys automatically.
- Requires an explicit browser confirmation and the exact backend confirmation phrase.
- Re-checks the submitted scan against the accumulated V18.3.78 evidence model.
- Only accepts STRONG_WOULD_BUY / WOULD_BUY evidence decisions.
- Uses a notional market order on the existing Alpaca TradingClient.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import Body, HTTPException, Request
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from backend.v18378_crypto_evidence_decision_engine import _build_model, _num, _score_bin

VERSION = "V18.3.79"
CONFIRMATION = "CONFIRM CRYPTO BUY"


def _normalise_symbol(value: Any) -> str:
    raw = str(value or "").upper().strip().replace("-", "/")
    if not raw:
        return ""
    if "/" in raw:
        base, quote = raw.split("/", 1)
        return f"{base}/{quote}"
    if raw.endswith("USD") and len(raw) > 3:
        return f"{raw[:-3]}/USD"
    return raw


def _evidence_verdict(m, scan: Dict[str, Any]) -> Dict[str, Any]:
    model = _build_model(m)
    positives = set(model.get("positiveSymbols") or [])
    negatives = set(model.get("negativeSymbols") or [])
    positive_bins = set(model.get("positiveScoreBins") or [])
    symbol_stats = model.get("symbolStats") or {}
    bin_stats = model.get("scoreBins") or {}

    symbol = _normalise_symbol(scan.get("symbol"))
    score = _num(scan.get("score"))
    band = _score_bin(score)
    sym = dict(symbol_stats.get(symbol) or {})
    bstat = dict(bin_stats.get(band) or {})
    backend_qualified = bool(scan.get("backendQualified", scan.get("qualified")))
    liquid = scan.get("liquid") is not False

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

    return {
        "symbol": symbol,
        "score": score,
        "scoreBin": band,
        "verdict": verdict,
        "reason": reason,
        "historicalExpectancyUsd": round(
            max(_num(sym.get("expectancyUsd")), _num(bstat.get("expectancyUsd"))), 5
        ),
        "evidenceTrades": max(int(sym.get("trades") or 0), int(bstat.get("trades") or 0)),
    }



def _alpaca_crypto_order_symbol(symbol: str) -> str:
    normalised = _normalise_symbol(symbol)
    if not normalised.endswith("/USD"):
        return ""
    return normalised.replace("/", "")


def _crypto_buying_power(account: Any) -> Dict[str, float]:
    total = max(0.0, _num(getattr(account, "buying_power", 0.0)))
    non_marginable = max(0.0, _num(getattr(account, "non_marginable_buying_power", 0.0)))
    cash = max(0.0, _num(getattr(account, "cash", 0.0)))

    # Alpaca crypto is non-marginable. If that field is available and positive,
    # it is the real ceiling for crypto even when stock buying_power is larger.
    usable = non_marginable if non_marginable > 0 else total
    if cash > 0:
        usable = min(usable, cash) if usable > 0 else cash

    return {
        "buyingPowerUsd": round(total, 2),
        "nonMarginableBuyingPowerUsd": round(non_marginable, 2),
        "cashUsd": round(cash, 2),
        "usableCryptoBuyingPowerUsd": round(max(0.0, usable), 2),
    }


def install_v18379_confirm_crypto_buy(app, m) -> None:
    @app.get("/v18/crypto-evidence/buy-preflight")
    def v18379_crypto_buy_preflight(request: Request):
        verify = getattr(m, "verify_api_key", None)
        if callable(verify):
            verify(request)

        account = m.trading_client.get_account()
        power = _crypto_buying_power(account)
        return {
            "ok": True,
            "version": VERSION,
            **power,
        }

    @app.post("/v18/crypto-evidence/confirm-buy")
    def v18379_confirm_crypto_buy(
        request: Request,
        payload: Dict[str, Any] = Body(default={}),
    ):
        verify = getattr(m, "verify_api_key", None)
        if callable(verify):
            verify(request)

        if str(payload.get("confirmation") or "") != CONFIRMATION:
            raise HTTPException(status_code=400, detail="Explicit confirmation required")

        scan = payload.get("scan")
        if not isinstance(scan, dict):
            raise HTTPException(status_code=400, detail="Evidence scan is required")

        amount = _num(payload.get("notionalUsd"))
        if amount < 1.0:
            raise HTTPException(status_code=400, detail="Minimum crypto buy is $1.00")

        account = m.trading_client.get_account()
        power = _crypto_buying_power(account)
        buying_power = _num(power.get("usableCryptoBuyingPowerUsd"))
        if buying_power <= 0:
            print(
                f"{VERSION} CONFIRMED CRYPTO BUY REJECTED | reason=NO_CRYPTO_BUYING_POWER "
                f"requested=${amount:.2f} account={power}",
                flush=True,
            )
            raise HTTPException(status_code=400, detail="No usable crypto buying power available")
        if amount > buying_power:
            print(
                f"{VERSION} CONFIRMED CRYPTO BUY REJECTED | reason=INSUFFICIENT_CRYPTO_BUYING_POWER "
                f"requested=${amount:.2f} usable=${buying_power:.2f} account={power}",
                flush=True,
            )
            raise HTTPException(
                status_code=400,
                detail=f"Requested ${amount:.2f} exceeds usable crypto buying power ${buying_power:.2f}",
            )

        decision = _evidence_verdict(m, scan)
        if decision["verdict"] not in ("STRONG_WOULD_BUY", "WOULD_BUY"):
            raise HTTPException(
                status_code=409,
                detail=f"Evidence no longer permits this manual buy: {decision['reason']}",
            )

        symbol = decision["symbol"]
        if not symbol.endswith("/USD"):
            raise HTTPException(status_code=400, detail="Only USD crypto pairs are supported")

        broker_symbol = _alpaca_crypto_order_symbol(symbol)
        if not broker_symbol:
            raise HTTPException(status_code=400, detail="Unable to convert crypto symbol for Alpaca")

        order = MarketOrderRequest(
            symbol=broker_symbol,
            notional=round(amount, 2),
            side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC,
        )
        try:
            submitted = m.trading_client.submit_order(order_data=order)
        except Exception as exc:
            print(
                f"{VERSION} CONFIRMED CRYPTO BUY BROKER REJECTED | symbol={symbol} "
                f"broker_symbol={broker_symbol} notional=${amount:.2f} "
                f"error={type(exc).__name__}: {exc}",
                flush=True,
            )
            raise HTTPException(
                status_code=400,
                detail=f"Alpaca rejected the crypto buy: {exc}",
            )
        order_id = str(getattr(submitted, "id", "") or "")

        print(
            f"{VERSION} USER CONFIRMED CRYPTO BUY | symbol={symbol} broker_symbol={broker_symbol} "
            f"notional=${amount:.2f} verdict={decision['verdict']} "
            f"score={decision['score']:.3f} evidence={decision['evidenceTrades']} "
            f"expectancy=${decision['historicalExpectancyUsd']:.5f} order_id={order_id or '-'}",
            flush=True,
        )

        return {
            "ok": True,
            "version": VERSION,
            "message": f"Confirmed crypto buy submitted for {symbol}.",
            "symbol": symbol,
            "brokerSymbol": broker_symbol,
            "notionalUsd": round(amount, 2),
            "orderId": order_id or None,
            "decision": decision,
        }

    print(
        f"{VERSION} CONFIRMED CRYPTO BUY | installed "
        "automatic_orders=False explicit_user_confirmation=True evidence_recheck=True",
        flush=True,
    )
