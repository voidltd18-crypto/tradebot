"""V19.0.11 observational sell submission telemetry.

Wraps the existing order function without changing its arguments, return value,
exceptions, or the decision to sell. Time measured is call duration, NOT broker
fill latency. Keeps no account identifiers or credentials.
"""
from __future__ import annotations
import threading
import time
from datetime import datetime, timezone
from fastapi import Request

_lock=threading.RLock()
_events=[]
_MAX_EVENTS=300

def _event(symbol, reason, elapsed, outcome, error_type=None):
    return {"atUtc":datetime.now(timezone.utc).isoformat(),
            "symbol":str(symbol).upper()[:24],
            "reason":str(reason or "")[:180],
            "callDurationMs":round(elapsed*1000,2),
            "outcome":outcome,
            "exceptionType":error_type,
            "brokerFillVerified":False}

def install_v19011_sell_telemetry(app,m):
    previous=m.market_sell_qty
    def observed_sell(symbol,qty,*args,**kwargs):
        reason=kwargs.get("reason",args[2] if len(args)>2 else "")
        start=time.monotonic()
        try:
            result=previous(symbol,qty,*args,**kwargs)
        except Exception as exc:
            ev=_event(symbol,reason,time.monotonic()-start,"exception",type(exc).__name__)
            with _lock:
                _events.append(ev)
                del _events[:-_MAX_EVENTS]
            print(f"V19.0.11 SELL CALL | symbol={ev['symbol']} outcome=exception duration_ms={ev['callDurationMs']} error={ev['exceptionType']}",flush=True)
            raise
        ev=_event(symbol,reason,time.monotonic()-start,"returned")
        with _lock:
            _events.append(ev)
            del _events[:-_MAX_EVENTS]
        print(f"V19.0.11 SELL CALL | symbol={ev['symbol']} outcome=returned duration_ms={ev['callDurationMs']} broker_fill=NOT_VERIFIED",flush=True)
        return result
    m.market_sell_qty=observed_sell
    @app.get("/v19/sell-execution-telemetry")
    def telemetry(request:Request,limit:int=100):
        m.verify_api_key(request)
        with _lock:
            events=list(_events[-max(1,min(int(limit),_MAX_EVENTS)):])
        return {"ok":True,"version":"V19.0.11","records":list(reversed(events)),
                "liveTradingRulesChanged":False,
                "note":"Only records sell-function call duration and exception; success does not establish order fill or execution price. In-memory rolling buffer resets on deploy."}
