"""Isolated read-only Smart Rebuy preview. Does not import TradeBot's trading app."""
import os
import secrets
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from backend.v19_manual_crypto_rebuy_preview import preview

app = FastAPI(title="Smart Rebuy isolated preview", docs_url=None, redoc_url=None, openapi_url=None)

@app.get("/health")
def health():
    return {"ok": True, "mode": "read-only", "brokerConfigured": bool(os.getenv("APCA_API_KEY_ID") and os.getenv("APCA_API_SECRET_KEY"))}

@app.get("/", response_class=HTMLResponse)
def home():
    # Token is entered in the browser and sent only in the authenticated request header.
    # Never put credentials in URLs, localStorage, cookies, or server-side HTML.
    html = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Smart Rebuy — read-only</title>
<style>
body{font:16px system-ui,sans-serif;background:#101827;color:#eef2ff;margin:0;padding:28px}
main{max-width:760px;margin:auto}h1{margin-bottom:4px}
p{color:#b7c4d9}label{display:block;margin:22px 0 8px}
input{box-sizing:border-box;width:100%;padding:13px;background:#202d40;color:white;border:1px solid #65748b;border-radius:8px}
button{background:#4b8cff;color:white;border:0;border-radius:8px;padding:12px 18px;margin-top:14px;cursor:pointer}
button:disabled{opacity:.5;cursor:wait}
section{background:#1c293c;border:1px solid #334155;border-radius:14px;padding:22px;margin-top:18px} .signal{display:flex;align-items:center;gap:14px;margin:14px 0} .light{width:28px;height:28px;border-radius:50%;flex-shrink:0} .red{background:#ef4444;box-shadow:0 0 0 5px #ef444422} .amber{background:#f59e0b;box-shadow:0 0 0 5px #f59e0b22} .green{background:#22c55e;box-shadow:0 0 0 5px #22c55e22} .status{font-size:24px;font-weight:750} .detail{color:#b7c4d9;margin:8px 0} .metrics{font-size:14px;color:#cbd5e1}
small{color:#a9b7c9}
</style></head><body><main><h1>Smart Rebuy</h1>
<p>Live Alpaca data · Read-only · No orders submitted</p>
<label for="token">Private preview token</label>
<input id="token" type="password" autocomplete="off" spellcheck="false" placeholder="Enter your Render preview token">
<button id="check">Check UNI/USD and ARB/USD</button>
<p><small>Your token is used only for these requests. It is not saved in your browser or displayed in the results.</small></p>
<div id="results" aria-live="polite"></div>\n<section><h2>Full Alpaca Account</h2><button id="accountCheck">Refresh account balance</button><div id="accountResults" aria-live="polite"><small>Enter your private preview token, then refresh to see live holdings.</small></div></section>
<script>
const btn=document.getElementById('check');
const output=document.getElementById('results');
btn.addEventListener('click',async()=>{
  const token=document.getElementById('token').value;
  if(!token){output.textContent='Enter your private preview token first.';return;}
  btn.disabled=true;output.textContent='Checking live broker data…';
  const symbols=['UNIUSD','ARBUSD'];
  const results=await Promise.all(symbols.map(async symbol=>{
    try{
      const response=await fetch('/preview/'+symbol,{headers:{'X-Preview-Token':token},cache:'no-store'});
      if(!response.ok)return {symbol,error:response.status===403?'Invalid preview token':'Request failed (HTTP '+response.status+')'};
      return {symbol,data:await response.json()};
    }catch(e){return {symbol,error:'Connection error'};}
  }));
  output.replaceChildren();
  for(const item of results){
    const section=document.createElement('section');
    const title=document.createElement('strong');
    title.textContent=item.symbol==='UNIUSD'?'UNI/USD':'ARB/USD';
    const data=item.data||{};
    const reason=String(data.reason||'No verified signal');
    const blocked=Boolean(item.error)||data.positionOpen===true||data.orderPending===true||
      /position|order pending|broker data unavailable|unverified|verified sale|credentials|invalid/i.test(reason);
    const green=!item.error&&data.status==='BUY_CANDIDATE'&&data.readOnly===true&&data.orderSubmitted===false;
    const colour=green?'green':blocked?'red':'amber';
    const label=green?'YES — Buy candidate':blocked?'NO — Blocked':'WAIT — Not ready';
    const signal=document.createElement('div');signal.className='signal';
    const light=document.createElement('span');light.className='light '+colour;
    light.setAttribute('aria-hidden','true');
    const status=document.createElement('span');status.className='status';status.textContent=label;
    signal.append(light,status);
    const message=document.createElement('p');message.className='detail';
    message.textContent=item.error||reason;
    section.append(title,signal,message);
    if(data.dipPct!=null){
      const metric=document.createElement('div');metric.className='metrics';
      metric.textContent='Dip from last sale: '+data.dipPct+'%';
      section.append(metric);
    }
    if(data.quoteFresh===false){
      const warning=document.createElement('p');warning.className='metrics';
      warning.textContent='Quote not fresh — no buy signal';
      section.append(warning);
    }
    output.append(section);
  }
  btn.disabled=false;
});

const accountBtn=document.getElementById('accountCheck');
const accountOutput=document.getElementById('accountResults');
const usd=v=>{const n=Number(v);return Number.isFinite(n)?new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(n):'—'};
const signed=v=>{const n=Number(v);return (n>0?'+':'')+usd(n)};
const accountLine=(label,value)=>{const p=document.createElement('p');p.className='metrics';p.textContent=label+': '+value;return p};
accountBtn.addEventListener('click',async()=>{
 const token=document.getElementById('token').value;
 if(!token){accountOutput.textContent='Enter your private preview token first.';return}
 accountBtn.disabled=true;accountOutput.textContent='Loading live account…';
 try{
  const r=await fetch('/account',{headers:{'X-Preview-Token':token},cache:'no-store'});
  if(!r.ok){accountOutput.textContent=r.status===403?'Invalid preview token':'Account unavailable (HTTP '+r.status+')';return}
  const a=await r.json();accountOutput.replaceChildren();
  const heading=document.createElement('h3');heading.textContent=a.mode+' account overview';accountOutput.append(heading);
  for(const [label,value] of [['Total equity',usd(a.equity)],['Previous equity',usd(a.previousEquity)],['Cash',usd(a.cash)],['Buying power',usd(a.buyingPower)],['Account today',signed(a.todayChange)+' ('+Number(a.todayChangePct).toFixed(2)+'%)']])accountOutput.append(accountLine(label,value));
  const filter=document.createElement('select');filter.setAttribute('aria-label','Filter holdings');
  for(const [v,label] of [['all','All holdings'],['us_equity','Stocks'],['crypto','Crypto']]){const opt=document.createElement('option');opt.value=v;opt.textContent=label;filter.append(opt)}
  filter.style.cssText='width:100%;padding:10px;background:#202d40;color:white;border-radius:8px;margin-top:12px';
  const list=document.createElement('div');accountOutput.append(filter,list);
  const render=()=>{list.replaceChildren();const items=a.positions.filter(p=>filter.value==='all'||p.assetClass===filter.value);
   const summary=document.createElement('p');summary.className='metrics';summary.textContent=items.length+' positions · Market value '+usd(items.reduce((t,p)=>t+Number(p.marketValue),0))+' · Unrealized P/L '+signed(items.reduce((t,p)=>t+Number(p.unrealizedPL),0));list.append(summary);
   for(const p of items){const box=document.createElement('section');const title=document.createElement('strong');title.textContent=p.symbol+' · '+p.assetClass;box.append(title);
    for(const [k,v] of [['Quantity',p.quantity],['Average buy',usd(p.averageBuy)],['Current price',usd(p.currentPrice)],['Cost basis',usd(p.costBasis)],['Market value',usd(p.marketValue)],['Overall P/L',signed(p.unrealizedPL)+' ('+Number(p.unrealizedPLPct).toFixed(2)+'%)'],["Today's P/L",signed(p.todayPL)+' ('+Number(p.todayPLPct).toFixed(2)+'%)']])box.append(accountLine(k,v));list.append(box)}
  };filter.addEventListener('change',render);render();
 }catch(e){accountOutput.textContent='Connection error retrieving account.'}finally{accountBtn.disabled=false}
});
</script></main></body></html>"""
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"})

@app.get("/preview/{symbol}")
def signal(symbol: str, x_preview_token: str = Header(default="")):
    token = os.getenv("SMART_REBUY_PREVIEW_TOKEN", "")
    if not token or not secrets.compare_digest(x_preview_token, token):
        raise HTTPException(status_code=403, detail="Preview access denied")
    key, secret = os.getenv("APCA_API_KEY_ID"), os.getenv("APCA_API_SECRET_KEY")
    if not key or not secret:
        return {"status": "WAIT", "readOnly": True, "orderSubmitted": False, "reason": "Broker credentials not configured"}
    from alpaca.trading.client import TradingClient
    from alpaca.data.historical import CryptoHistoricalDataClient
    return preview(TradingClient(key, secret, paper=os.getenv("APCA_API_PAPER", "false").lower() == "true"),
                   CryptoHistoricalDataClient(key, secret), symbol)

@app.get("/account")
def account_overview(x_preview_token: str = Header(default="")):
    """Authenticated, read-only Alpaca equity, positions and intraday P/L."""
    token = os.getenv("SMART_REBUY_PREVIEW_TOKEN", "")
    if not token or not secrets.compare_digest(x_preview_token, token):
        raise HTTPException(status_code=403, detail="Preview access denied")
    key, secret = os.getenv("APCA_API_KEY_ID"), os.getenv("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise HTTPException(status_code=503, detail="Broker credentials not configured")
    from decimal import Decimal
    from alpaca.trading.client import TradingClient
    from fastapi.responses import JSONResponse
    client = TradingClient(key, secret, paper=os.getenv("APCA_API_PAPER", "false").lower() == "true")
    try:
        account = client.get_account()
        positions = client.get_all_positions()
    except Exception:
        raise HTTPException(status_code=502, detail="Unable to retrieve broker account data")
    def dec(value):
        return Decimal(str(value)) if value is not None and str(value) != "" else Decimal("0")
    def fmt(value):
        return str(value)
    equity, prior = dec(account.equity), dec(account.last_equity)
    change = equity - prior
    result = []
    for p in positions:
        asset_class = str(getattr(p.asset_class, "value", p.asset_class)).lower()
        result.append({
            "symbol": p.symbol, "assetClass": asset_class,
            "quantity": fmt(dec(p.qty)), "averageBuy": fmt(dec(p.avg_entry_price)),
            "currentPrice": fmt(dec(p.current_price)), "costBasis": fmt(dec(p.cost_basis)),
            "marketValue": fmt(dec(p.market_value)),
            "unrealizedPL": fmt(dec(p.unrealized_pl)),
            "unrealizedPLPct": fmt(dec(p.unrealized_plpc) * 100),
            "todayPL": fmt(dec(p.unrealized_intraday_pl)),
            "todayPLPct": fmt(dec(p.unrealized_intraday_plpc) * 100)
        })
    return JSONResponse({
        "mode": "PAPER" if os.getenv("APCA_API_PAPER", "false").lower() == "true" else "LIVE",
        "equity": fmt(equity), "previousEquity": fmt(prior),
        "cash": fmt(dec(account.cash)), "buyingPower": fmt(dec(account.buying_power)),
        "todayChange": fmt(change),
        "todayChangePct": fmt(change / prior * 100 if prior else Decimal("0")),
        "positions": result, "readOnly": True
    }, headers={"Cache-Control": "no-store"})
