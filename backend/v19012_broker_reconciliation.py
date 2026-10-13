"""V19.0.12 observational sell-to-broker-order reconciliation.

No orders submitted, changed or cancelled. Symbol/time proximity only is NOT
a definitive causal match. Ambiguous candidates are explicitly reported.
"""
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import Request

def _dt(v):
    if isinstance(v,datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        x=datetime.fromisoformat(str(v).replace("Z","+00:00"))
        return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except (ValueError,TypeError):return None

def _field(o,key):
    return o.get(key) if isinstance(o,dict) else getattr(o,key,None)

def reconcile(events, orders, window_seconds=120):
    out=[]
    for event in events:
        stamped=_dt(event.get("atUtc"))
        symbol=str(event.get("symbol") or "").upper()
        matches=[]
        for order in orders:
            if str(_field(order,"symbol") or "").upper()!=symbol:continue
            side=str(_field(order,"side") or "").lower()
            if side not in ("sell","orderside.sell"):continue
            created=_dt(_field(order,"created_at") or _field(order,"submitted_at"))
            if not stamped or not created:continue
            delta=(created-stamped).total_seconds()
            if abs(delta)>window_seconds:continue
            filled=_dt(_field(order,"filled_at"))
            matches.append({
                "orderId":str(_field(order,"id") or ""),
                "status":str(_field(order,"status") or ""),
                "createdAtUtc":created.isoformat(),
                "filledAtUtc":filled.isoformat() if filled else None,
                "filledAvgPrice":str(_field(order,"filled_avg_price") or ""),
                "filledQty":str(_field(order,"filled_qty") or ""),
                "secondsFromCallReturnToOrderCreated":round(delta,2),
                "secondsFromOrderCreatedToFilled":round((filled-created).total_seconds(),2) if filled else None})
        out.append({**event,"candidateCount":len(matches),
                    "matchStatus":"ONE_TIME_CANDIDATE_NOT_PROOF" if len(matches)==1 else ("AMBIGUOUS" if matches else "NO_CANDIDATE"),
                    "brokerOrderCandidates":matches})
    return out

def install_v19012_broker_reconciliation(app,m):
    from backend import v19011_sell_telemetry as telemetry
    @app.get("/v19/sell-order-reconciliation")
    def endpoint(request:Request,limit:int=50):
        m.verify_api_key(request)
        with telemetry._lock:
            events=list(telemetry._events[-max(1,min(int(limit),100)):])
        try:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus
            request_obj=GetOrdersRequest(status=QueryOrderStatus.ALL,limit=500)
            orders=list(m.trading_client.get_orders(filter=request_obj) or [])
        except Exception as exc:
            return {"ok":False,"version":"V19.0.12","eventsRecorded":len(events),
                    "errorType":type(exc).__name__,"message":"Broker order lookup unavailable",
                    "liveTradingRulesChanged":False}
        records=reconcile(list(reversed(events)),orders)
        return {"ok":True,"version":"V19.0.12","eventsRecorded":len(events),
                "brokerOrdersChecked":len(orders),"records":records,
                "liveTradingRulesChanged":False,
                "warning":"Matches are candidate links by symbol and time only. Not proof a particular decision created an order. Call timestamps are recorded after the function returns; returned != broker accepted. Historic orders may be excluded by the broker's 500-order response limit."}
