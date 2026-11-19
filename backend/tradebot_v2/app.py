"""Isolated read-only TradeBot 2.0 dashboard. No trading API calls."""
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from backend.tradebot_v2.store import read_verified_ownership
from backend.tradebot_v2.research import evaluate_history
from backend.tradebot_v2.engine import (
    TECH_UNIVERSE, OrderRecord, Position, entry_gate, evaluate_pullback,
)

app = FastAPI(title="TradeBot 2.0 — read-only", docs_url=None, redoc_url=None, openapi_url=None)


def authorize(token: str):
    expected = os.getenv("SMART_REBUY_PREVIEW_TOKEN", "")
    if not expected or not secrets.compare_digest(token, expected):
        raise HTTPException(403, "Access denied")


def ledger_health():
    """Check database connectivity without exposing credentials or account data."""
    url = os.getenv("TRADEBOT_V2_DATABASE_URL")
    if not url:
        return {"configured": False, "reachable": False, "schemaReady": False}
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=4) as conn:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute("SELECT to_regclass('public.tradebot_v2_fill_events') IS NOT NULL")
                schema_ready = bool(cur.fetchone()[0])
        return {"configured": True, "reachable": True, "schemaReady": schema_ready}
    except Exception:
        return {"configured": True, "reachable": False, "schemaReady": False}


@app.get("/health")
def health():
    return {"ok": True, "version": "2.0", "readOnly": True, "tradingEnabled": False, "brokerConfigured": bool(os.getenv("APCA_API_KEY_ID") and os.getenv("APCA_API_SECRET_KEY")), "previewTokenConfigured": bool(os.getenv("SMART_REBUY_PREVIEW_TOKEN")), "ledger": ledger_health()}


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
    ownership = read_verified_ownership(os.getenv("TRADEBOT_V2_DATABASE_URL"), {p.symbol: float(p.qty) for p in broker_positions})
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
    research_stats = []
    for symbol in sorted(TECH_UNIVERSE):
        closes = [float(bar.close) for bar in bars.data.get(symbol, [])]
        research_stats.append(evaluate_history(symbol, closes).__dict__)
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
        # Separate hypothetical research signal from real-account entry eligibility.
        # Existing broker holdings always block real orders; no managed ledger is inferred.
        research = evaluate_pullback(symbol, [float(bar.close) for bar in bars.data.get(symbol, [])])
        signals.append({
            "symbol": symbol, "status": final.status, "reason": final.reason,
            "researchStatus": research.status, "researchReason": research.reason,
            "brokerEntryBlocked": gate.status == "RED",
        })
    return JSONResponse({
        "readOnly": True, "tradingEnabled": False, "asOf": now.isoformat(),
        "account": {"equity": str(account.equity), "cash": str(account.cash)},
        "positions": [{"symbol": p.symbol, "quantity": p.quantity} for p in positions],
        "positionLimit": 2,
        "positionLimitScope": "whole broker account",
        "managedPositions": [{"symbol": k, "quantity": v} for k, v in ownership.managed.items()] if ownership.verified else [],
        "managedPositionsConfigured": ownership.verified,
        "ownershipStatus": ownership.reason,
        "researchMode": "hypothetical signals only; no virtual fills or profit claims",
        "availableCash": str(account.cash),
        "signals": signals,
        "historicalResearch": research_stats,
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
<div id="account" class="grid"></div><h2>Market research signals</h2><p>Independent of your existing holdings. These are hypothetical setups, not executable orders.</p><div id="research" class="grid"></div><h2>Historical signal research</h2><p>Five-session forward price changes after green signals; not trading P/L. Small samples are unreliable.</p><div id="backtest" class="grid"></div><h2>Real-account safety checks</h2><div id="signals" class="grid"></div>
<p><small>Green = research candidate, NOT permission to buy. Red = blocked. Amber = wait. Two-position limit currently covers the whole Alpaca account. Research signals ignore holdings to show market setups, but account safeguards still block real entries. Bot-managed tracking requires a verified persistent ledger. No orders are enabled.</small></p>
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
 el('account').replaceChildren();for(const [name,val] of [['Account equity',money(data.account.equity)],['Cash',money(data.account.cash)],['Broker positions',String(data.positions.length)],['Bot-managed positions',data.managedPositionsConfigured?String(data.managedPositions.length):'Unverified'],['Available cash',money(data.availableCash)]]){
 const card=document.createElement('div');card.className='card';card.textContent=name+': '+val;el('account').append(card)}
 let note=el('ownershipNote');if(!note){note=document.createElement('p');note.id='ownershipNote';el('account').after(note)}note.textContent='Ownership: '+data.ownershipStatus;
 el('research').replaceChildren();for(const signal of data.signals){
 const card=document.createElement('div');card.className='card';
 const title=document.createElement('h3');title.textContent=signal.symbol+' · '+signal.researchStatus;title.className=signal.researchStatus.toLowerCase();
 const desc=document.createElement('p');desc.textContent=signal.researchReason;card.append(title,desc);el('research').append(card)}
 el('backtest').replaceChildren();for(const item of data.historicalResearch||[]){
 const card=document.createElement('div');card.className='card';
 const h=document.createElement('h3');h.textContent=item.symbol;card.append(h);
 const p=document.createElement('p');p.textContent=item.green_signals+' green signals · '+item.evaluated_signals+' with 5-session follow-up · '+(item.average_forward_5_bar_pct===null?'No measured follow-up':item.average_forward_5_bar_pct.toFixed(2)+'% mean subsequent price change');card.append(p);el('backtest').append(card)}
 el('signals').replaceChildren();for(const signal of data.signals){
 const card=document.createElement('div');card.className='card';
 const title=document.createElement('h3');title.textContent=signal.symbol+' · '+signal.status;title.className=signal.status.toLowerCase();
 const desc=document.createElement('p');desc.textContent=signal.reason;card.append(title,desc);el('signals').append(card)}
 }catch(e){el('status').textContent='Network error. No trades submitted.'}
 finally{el('refresh').disabled=false}
};
</script></main></html>"""
