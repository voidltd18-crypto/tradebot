import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from backend.engines.crypto_engine import CryptoEngine
from backend.engines.stock_engine import StockEngine

DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "")

app = FastAPI(title="Merged TradeBot Platform - Kraken + Alpaca")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

crypto = CryptoEngine()
stock = StockEngine()

def verify(request: Request):
    if not DASHBOARD_API_KEY:
        return
    if request.headers.get("x-api-key") != DASHBOARD_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

@app.get("/")
def root():
    return {"ok": True, "name": "Merged TradeBot Platform", "crypto": "Kraken", "stocks": "Alpaca PDT-safe"}

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/status")
def status():
    return {"ok": True, "crypto": crypto.status(), "stock": stock.status()}

@app.post("/start-crypto")
def start_crypto(request: Request):
    verify(request)
    return crypto.start()

@app.post("/stop-crypto")
def stop_crypto(request: Request):
    verify(request)
    return crypto.stop()

@app.post("/start-stock")
def start_stock(request: Request):
    verify(request)
    return stock.start()

@app.post("/stop-stock")
def stop_stock(request: Request):
    verify(request)
    return stock.stop()

@app.post("/stop-all")
def stop_all(request: Request):
    verify(request)
    c = crypto.stop()
    s = stock.stop()
    return {"ok": True, "crypto": c, "stock": s}
