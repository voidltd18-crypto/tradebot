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
section{background:#1c293c;border-radius:10px;padding:18px;margin-top:18px;white-space:pre-wrap;overflow-wrap:anywhere}
small{color:#a9b7c9}
</style></head><body><main><h1>Smart Rebuy</h1>
<p>Live Alpaca data · Read-only · No orders submitted</p>
<label for="token">Private preview token</label>
<input id="token" type="password" autocomplete="off" spellcheck="false" placeholder="Enter your Render preview token">
<button id="check">Check UNI/USD and ARB/USD</button>
<p><small>Your token is used only for these requests. It is not saved in your browser or displayed in the results.</small></p>
<div id="results" aria-live="polite"></div>
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
    const details=document.createElement('pre');
    details.style.whiteSpace='pre-wrap';
    details.style.overflowWrap='anywhere';
    details.textContent=item.error||JSON.stringify(item.data,null,2);
    section.append(title,details);output.append(section);
  }
  btn.disabled=false;
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
