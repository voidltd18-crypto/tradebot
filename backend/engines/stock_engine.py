from backend.services.alpaca_service import AlpacaService

class StockEngine:
    def __init__(self):
        self.service = AlpacaService()
        self.running = False
        self.logs = []

    def start(self):
        self.running = True
        self.logs.append("Stock engine enabled in PDT-safe swing mode")
        return {"ok": True, "message": "Stock engine enabled"}

    def stop(self):
        self.running = False
        return {"ok": True, "message": "Stock engine stopped"}

    def status(self):
        return {"running": self.running, "service": self.service.status(), "logs": self.logs[-50:]}
