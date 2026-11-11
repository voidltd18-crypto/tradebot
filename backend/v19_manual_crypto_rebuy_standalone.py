"""Isolated read-only Smart Rebuy preview. Does not import TradeBot's trading app."""
import os
import secrets
from fastapi import FastAPI, Header, HTTPException
from backend.v19_manual_crypto_rebuy_preview import preview

app = FastAPI(title="Smart Rebuy isolated preview", docs_url=None, redoc_url=None, openapi_url=None)

@app.get("/health")
def health():
    return {"ok": True, "mode": "read-only", "brokerConfigured": bool(os.getenv("APCA_API_KEY_ID") and os.getenv("APCA_API_SECRET_KEY"))}

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
    # Only the preview function uses read operations; never run the legacy trading app.
    return preview(TradingClient(key, secret, paper=os.getenv("APCA_API_PAPER", "false").lower() == "true"),
                   CryptoHistoricalDataClient(key, secret), symbol)
