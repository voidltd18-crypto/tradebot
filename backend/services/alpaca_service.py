import os
from typing import Dict, Any

class AlpacaService:
    def __init__(self):
        self.api_key = os.getenv("ALPACA_API_KEY", os.getenv("APCA_API_KEY_ID", ""))
        self.secret = os.getenv("ALPACA_SECRET_KEY", os.getenv("APCA_API_SECRET_KEY", ""))
        self.no_same_day_sells = os.getenv("STOCK_NO_SAME_DAY_SELLS", "true").lower() == "true"
        self.dry_run = os.getenv("DRY_RUN", "true").lower() == "true"

    def status(self) -> Dict[str, Any]:
        return {
            "configured": bool(self.api_key and self.secret),
            "dryRun": self.dry_run,
            "noSameDaySells": self.no_same_day_sells,
            "note": "Stock engine is PDT-safe swing mode in this merged build. Your previous full Alpaca engine can be dropped into backend/engines/stock_engine.py later.",
        }
