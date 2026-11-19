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
<section><h2>Holdings performance</h2><p><small>Historical market prices · Current share quantities · Not historical account equity</small></p><div id="chartRanges"></div><div id="chartStatus" class="metrics">Enter your token and choose a range.</div><div id="chartLegend" class="metrics"></div><div id="moneySummary" class="metrics" style="margin:14px 0"></div><svg id="holdingsChart" viewBox="0 0 720 300" role="img" aria-label="Combined holdings performance chart" style="width:100%;height:auto;display:none"></svg></section>
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

const ranges=['1D','5D','1M','3M','1Y','ALL'];
const chartRanges=document.getElementById('chartRanges'),chartStatus=document.getElementById('chartStatus');
const chart=document.getElementById('holdingsChart'),chartLegend=document.getElementById('chartLegend');
let chartRange='5D';
function svgNode(tag,attrs){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));return n}
async function loadChart(){
 const token=document.getElementById('token').value;
 if(!token){chartStatus.textContent='Enter your private preview token first.';return}
 chartStatus.textContent='Loading historical stock prices…';chart.style.display='none';
 try{
  const r=await fetch('/holdings-history?range='+encodeURIComponent(chartRange),{headers:{'X-Preview-Token':token},cache:'no-store'});
  if(!r.ok){chartStatus.textContent=r.status===403?'Invalid preview token':'Historical prices unavailable (HTTP '+r.status+')';return}
  const data=await r.json(),series=data.series||[];
  if(!series.length||!series.some(s=>s.points.length>1)){chartStatus.textContent='Not enough market history for this range.';return}
  const m=data.money;
  if(m&&Number(m.costBasis)>0){
    const combined=series.find(s=>s.symbol==='Combined');
    if(combined&&combined.points.length){
      const last=combined.points[combined.points.length-1];
      combined.points.push([Math.max(Date.now(),last[0]+1),100*(Number(m.currentValue)/Number(m.costBasis)-1)]);
    }
  }
  const values=series.flatMap(s=>s.points.map(p=>p[1])).concat([0]);
  let lo=Math.min(...values),hi=Math.max(...values);if(hi===lo){lo-=1;hi+=1}
  const pad=(hi-lo)*.12;lo-=pad;hi+=pad;
  const times=series.flatMap(s=>s.points.map(p=>p[0])),minT=Math.min(...times),maxT=Math.max(...times);
  const X=t=>55+(t-minT)/Math.max(1,maxT-minT)*645,Y=v=>260-(v-lo)/(hi-lo)*220;
  chart.replaceChildren();const gridColor='#526176';
  for(let i=0;i<=4;i++){const v=lo+(hi-lo)*i,y=Y(v);chart.append(svgNode('line',{x1:55,y1:y,x2:700,y2:y,stroke:gridColor,'stroke-opacity':'.35'}));const label=svgNode('text',{x:47,y:y+4,fill:'#cbd5e1','font-size':12,'text-anchor':'end'});label.textContent=v.toFixed(1)+'%';chart.append(label)}
  chart.append(svgNode('line',{x1:55,y1:Y(0),x2:700,y2:Y(0),stroke:'#ef4444','stroke-width':2,'stroke-dasharray':'7 5'}));
  const colors={'MSFT':'#60a5fa','NVDA':'#f59e0b','Combined':'#34d399'};
  chartLegend.replaceChildren();const baseline=document.createElement('span');baseline.style.cssText='display:inline-block;margin:8px 16px 0 0;color:#ef4444';baseline.textContent='┄ Starting investment (0%)';chartLegend.append(baseline);
  for(const s of series){if(s.points.length<2)continue;const points=s.points.map(p=>X(p[0]).toFixed(1)+','+Y(p[1]).toFixed(1)).join(' ');
   chart.append(svgNode('polyline',{points,fill:'none',stroke:colors[s.symbol]||'#d8b4fe','stroke-width':s.symbol==='Combined'?3.5:2.5,'stroke-linejoin':'round'}));
   const last=s.points[s.points.length-1][1];const label=document.createElement('span');label.style.cssText='display:inline-block;margin:8px 16px 0 0;color:'+(colors[s.symbol]||'#d8b4fe');label.textContent='● '+s.symbol+' '+(last>=0?'+':'')+last.toFixed(2)+'%';chartLegend.append(label)}
  const summary=document.getElementById('moneySummary');summary.textContent=m?'Starting investment '+usd(m.costBasis)+'  ·  Holdings now '+usd(m.currentValue)+'  ·  P/L '+signed(Number(m.currentValue)-Number(m.costBasis))+'  ·  Full account equity '+usd(data.accountEquity):'Holdings figures unavailable';
  chart.style.display='block';chartStatus.textContent='Split-adjusted prices; the latest combined point uses live holdings. '+(chartRange==='ALL'&&!data.holdingStartVerified?'Purchase date unavailable: showing up to 30 days. ':'')+'Not historical account equity.';
 }catch(e){chartStatus.textContent='Unable to load historical price chart.'}
}

for(const range of ranges){const b=document.createElement('button');b.textContent=range;b.style.marginRight='6px';b.addEventListener('click',()=>{chartRange=range;loadChart()});chartRanges.append(b)}
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

@app.get("/holdings-history")
def holdings_history(range: str = "5D", x_preview_token: str = Header(default="")):
    """Read-only price histories for material US equity holdings, weighted by current quantities."""
    token = os.getenv("SMART_REBUY_PREVIEW_TOKEN", "")
    if not token or not secrets.compare_digest(x_preview_token, token):
        raise HTTPException(status_code=403, detail="Preview access denied")
    key, secret = os.getenv("APCA_API_KEY_ID"), os.getenv("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise HTTPException(status_code=503, detail="Broker credentials not configured")
    from datetime import datetime, timedelta, timezone
    from alpaca.trading.client import TradingClient
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.data.enums import DataFeed, Adjustment
    from fastapi.responses import JSONResponse
    options = {"1D": (2, True), "5D": (9, True), "1M": (35, False),
               "3M": (100, False), "1Y": (375, False), "ALL": (1825, False)}
    if range not in options:
        raise HTTPException(status_code=400, detail="Invalid chart range")
    days, intraday = options[range]
    try:
        broker = TradingClient(key, secret, paper=os.getenv("APCA_API_PAPER", "false").lower() == "true")
        account_equity = float(broker.get_account().equity)
        positions = [p for p in broker.get_all_positions()
                     if str(getattr(p.asset_class, "value", p.asset_class)).lower() == "us_equity"
                     and abs(float(p.market_value)) >= 0.01 and float(p.qty) > 0]
        positions = sorted(positions, key=lambda p: abs(float(p.market_value)), reverse=True)[:10]
        if not positions:
            return JSONResponse({"series": []}, headers={"Cache-Control": "no-store"})
        now = datetime.now(timezone.utc)
        holding_start = None
        try:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus
            orders = broker.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=500))
            symbols_held = {p.symbol for p in positions}
            buys = [o.filled_at for o in orders if o.symbol in symbols_held and
                    str(getattr(o.side, "value", o.side)).lower() == "buy" and getattr(o, "filled_at", None)]
            if buys:
                holding_start = min(buys)
        except Exception:
            pass
        if range == "ALL":
            days = 30 if holding_start is None else max(2, min(1825, (now-holding_start).days+2))
        if range == "ALL" and days <= 9:
            intraday = True
        request = StockBarsRequest(symbol_or_symbols=[p.symbol for p in positions],
                                   timeframe=TimeFrame.Minute if intraday else TimeFrame.Day,
                                   start=now-timedelta(days=days), end=now,
                                   feed=DataFeed.IEX, adjustment=Adjustment.ALL, limit=10000)
        bars = StockHistoricalDataClient(key, secret).get_stock_bars(request)
        raw = {}
        for p in positions:
            values = [(int(b.timestamp.timestamp()*1000), float(b.close)) for b in bars.data.get(p.symbol, [])]
            values.sort()
            if range == "1D" and values:
                latest_day = datetime.fromtimestamp(values[-1][0]/1000, timezone.utc).date()
                values = [v for v in values if datetime.fromtimestamp(v[0]/1000, timezone.utc).date() == latest_day]
            if range == "ALL" and holding_start is not None:
                cutoff = int(holding_start.timestamp()*1000)
                values = [v for v in values if v[0] >= cutoff]
            raw[p.symbol] = values
        series = []
        money = None
        for symbol, values in raw.items():
            if len(values) < 2 or not values[0][1]:
                continue
            position = next(p for p in positions if p.symbol == symbol)
            base = float(position.avg_entry_price)
            if base <= 0:
                continue
            series.append({"symbol": symbol, "points": [[t, round((price/base-1)*100, 4)] for t, price in values]})
        # Use aligned timestamps only; a historical reconstruction of current positions, not past account equity.
        available = {p.symbol: {t: price for t, price in raw[p.symbol]} for p in positions}
        symbols = [p.symbol for p in positions if len(raw[p.symbol]) > 1]
        if symbols:
            common = sorted(set.intersection(*(set(available[s]) for s in symbols)))
            if len(common) > 1:
                quantities = {p.symbol: float(p.qty) for p in positions}
                baseline = sum(float(p.cost_basis) for p in positions if p.symbol in symbols)
                if baseline:
                    money = {"costBasis": round(sum(float(p.cost_basis) for p in positions if p.symbol in symbols), 4),
                             "currentValue": round(sum(float(p.market_value) for p in positions if p.symbol in symbols), 4),
                             "points": [[t, round(sum(available[s][t]*quantities[s] for s in symbols), 4)] for t in common]}
                    series.append({"symbol": "Combined", "points": [
                        [t, round((sum(available[s][t]*quantities[s] for s in symbols)/baseline-1)*100, 4)]
                        for t in common]})
        return JSONResponse({"range": range, "series": series, "money": money, "accountEquity": account_equity, "holdingStartVerified": holding_start is not None, "readOnly": True},
                            headers={"Cache-Control": "no-store"})
    except Exception:
        raise HTTPException(status_code=502, detail="Historical market data unavailable")
