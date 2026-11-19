"""Isolated read-only TradeBot 2.0 dashboard. No trading API calls."""
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from backend.tradebot_v2.engine import (
    TECH_UNIVERSE, OrderRecord, Position, entry_gate, evaluate_pullback,
)

app = FastAPI(title="TradeBot 2.0 — read-only", docs_url=None, redoc_url=None, openapi_url=None)


def authorize(token: str):
    expected = os.getenv("SMART_REBUY_PREVIEW_TOKEN", "")
    if not expected or not secrets.compare_digest(token, expected):
        raise HTTPException(403, "Access denied")


@app.get("/health")
def health():
    return {"ok": True, "version": "2.0", "readOnly": True, "tradingEnabled": False, "brokerConfigured": bool(os.getenv("APCA_API_KEY_ID") and os.getenv("APCA_API_SECRET_KEY")), "previewTokenConfigured": bool(os.getenv("SMART_REBUY_PREVIEW_TOKEN"))}


@app.get("/api/scan")
def scan(x_preview_token: str = Header(default="")):
    authorize(x_preview_token)
    key, secret = os.getenv("APCA_API_KEY_ID"), os.getenv("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise HTTPException(503, "Broker data not configured")
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.data.enums import DataFeed, Adjustment

    now = datetime.now(timezone.utc)
    try:
        broker = TradingClient(key, secret, paper=os.getenv("APCA_API_PAPER", "false").lower() == "true")
        account = broker.get_account()
        broker_positions = broker.get_all_positions()
        # Broker history is required: if it cannot be checked, fail closed.
        orders = broker.get_orders(filter=GetOrdersRequest(
            status=QueryOrderStatus.ALL, after=now-timedelta(days=3), limit=500,
            nested=False, direction="desc",
        ))
    except Exception:
        raise HTTPException(502, "Broker account or order history unavailable; all entries blocked")

    positions = [Position(p.symbol, float(p.qty)) for p in broker_positions if float(p.qty) != 0]
    history = []
    for o in orders:
        created = getattr(o, "filled_at", None) or getattr(o, "created_at", None)
        if created is None:
            raise HTTPException(502, "Order history contains missing timestamps; entries blocked")
        history.append(OrderRecord(
            symbol=o.symbol,
            side=str(getattr(o.side, "value", o.side)),
            created_at=created,
            status=str(getattr(o.status, "value", o.status)),
        ))
    # Never infer a clean history from a potentially truncated page.
    if len(orders) >= 500:
        raise HTTPException(502, "Order history may be truncated; entries blocked")

    try:
        data = StockHistoricalDataClient(key, secret)
        bars = data.get_stock_bars(StockBarsRequest(
            symbol_or_symbols=sorted(TECH_UNIVERSE),
            timeframe=TimeFrame.Day,
            start=now-timedelta(days=65),
            end=now,
            feed=DataFeed.IEX,
            adjustment=Adjustment.ALL,
        ))
    except Exception:
        raise HTTPException(502, "Market data unavailable; entries blocked")

    signals = []
    for symbol in sorted(TECH_UNIVERSE):
        gate = entry_gate(symbol, positions, history, now)
        if gate.status == "RED":
            final = gate
        else:
            closes = [float(bar.close) for bar in bars.data.get(symbol, [])]
            technical = evaluate_pullback(symbol, closes)
            # A green research setup is NOT an order authorization.
            if gate.status == "AMBER" and "cooldown" in gate.reason.lower():
                final = gate
            elif technical.status == "GREEN":
                final = type(gate)(symbol, "GREEN", "Research-only pullback candidate; no orders enabled")
            else:
                final = technical
        signals.append({"symbol": symbol, "status": final.status, "reason": final.reason})
    return JSONResponse({
        "readOnly": True, "tradingEnabled": False, "asOf": now.isoformat(),
        "account": {"equity": str(account.equity), "cash": str(account.cash)},
        "positions": [{"symbol": p.symbol, "quantity": p.quantity} for p in positions],
        "positionLimit": 2,
        "positionLimitScope": "whole broker account",
        "managedPositions": [],
        "managedPositionsConfigured": False,
        "signals": signals,
    }, headers={"Cache-Control": "no-store"})


@app.get("/", response_class=HTMLResponse)
def home():
    return """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TradeBot 2.0</title>
<style>
body{font:16px system-ui;background:#0f172a;color:#f1f5f9;margin:0;padding:22px}
main{max-width:850px;margin:auto}p,small{color:#aebed0}
input,button{padding:12px;border-radius:9px;font:inherit}
input{background:#1e293b;color:white;border:1px solid #64748b;max-width:300px;width:90%}
button{background:#2563eb;color:white;border:0;cursor:pointer}
.card{background:#1e293b;border:1px solid #334155;border-radius:14px;padding:16px;margin:10px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}
.green{color:#4ade80}.amber{color:#fbbf24}.red{color:#fb7185}
</style><main><h1>TradeBot 2.0</h1><p>Live broker data · Research signals only · Trading disabled</p>
<input type="password" id="token" placeholder="Private preview token" autocomplete="off">
<button id="refresh">Scan stocks</button><p id="status">Enter token to load.</p>
<div id="account" class="grid"></div><h2>Tech stock scanner</h2><div id="signals" class="grid"></div>
<p><small>Green = research candidate, NOT permission to buy. Red = blocked. Amber = wait. Two-position limit currently covers the whole Alpaca account. Existing holdings are never automatically assigned to this bot. No orders are enabled.</small></p>
<script>
const el=id=>document.getElementById(id);
el('refresh').onclick=async()=>{
 const token=el('token').value;if(!token){el('status').textContent='Enter your token';return}
 el('refresh').disabled=true;el('status').textContent='Reading broker positions, order history and prices…';
 try{
 const response=await fetch('/api/scan',{headers:{'X-Preview-Token':token},cache:'no-store'});
 if(!response.ok){el('status').textContent='Unable to scan (HTTP '+response.status+'). No trading possible.';return}
 const data=await response.json();el('status').textContent='Updated '+new Date(data.asOf).toLocaleString()+' · Read-only';
 const money=n=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(Number(n));
 el('account').replaceChildren();for(const [name,val] of [['Account equity',money(data.account.equity)],['Cash',money(data.account.cash)],['Broker positions',String(data.positions.length)],['Bot-managed positions','Not configured']]){
 const card=document.createElement('div');card.className='card';card.textContent=name+': '+val;el('account').append(card)}
 el('signals').replaceChildren();for(const signal of data.signals){
 const card=document.createElement('div');card.className='card';
 const title=document.createElement('h3');title.textContent=signal.symbol+' · '+signal.status;title.className=signal.status.toLowerCase();
 const desc=document.createElement('p');desc.textContent=signal.reason;card.append(title,desc);el('signals').append(card)}
 }catch(e){el('status').textContent='Network error. No trades submitted.'}
 finally{el('refresh').disabled=false}
};
</script></main></html>"""
