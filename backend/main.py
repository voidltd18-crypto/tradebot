"""TradeBot FastAPI entry point.

V12.2 begins the safe modular migration without changing live behaviour.
The proven V12.1 application remains intact in ``backend.legacy.monolith``
while new services are extracted incrementally behind stable interfaces.

Render command remains:
    uvicorn backend.main:app --host 0.0.0.0 --port $PORT
"""
from backend.legacy import monolith
from backend.v18343_stock_leak import install_v18343
from backend.v18344_replay_lab import install_v18344_replay_lab
from backend.v18350_exit_incident_audit import install_v18350_exit_incident_audit
from backend.v18351_live_stock_replay_capture import install_v18351_live_stock_replay_capture
from backend.v18354_crypto_evidence_accelerator import install_v18354_historical_evidence_accelerator

app = monolith.app
install_v18343(app, monolith)
install_v18344_replay_lab(app, monolith)
install_v18350_exit_incident_audit(app, monolith)
install_v18351_live_stock_replay_capture(app, monolith)
install_v18354_historical_evidence_accelerator(app, monolith)

__all__ = ["app"]
