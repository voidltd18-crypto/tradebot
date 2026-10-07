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
from backend.v18357_capital_earnback_ladder import install_v18357_capital_earnback_ladder
from backend.v18360_ai_exit_manager import install_v18360_ai_exit_manager
from backend.v18361_ai_exit_outcome_scorer import install_v18361_ai_exit_outcome_scorer
from backend.v18362_ai_exit_learner import install_v18362_ai_exit_learner
from backend.v18363_ai_exit_live_pilot import install_v18363_ai_exit_live_pilot
from backend.v18364_ai_exit_pilot_guardian import install_v18364_ai_exit_pilot_guardian

app = monolith.app
install_v18343(app, monolith)
install_v18344_replay_lab(app, monolith)
install_v18350_exit_incident_audit(app, monolith)
install_v18351_live_stock_replay_capture(app, monolith)
install_v18354_historical_evidence_accelerator(app, monolith)
install_v18357_capital_earnback_ladder(app, monolith)
install_v18360_ai_exit_manager(app, monolith)
install_v18361_ai_exit_outcome_scorer(app, monolith)
install_v18362_ai_exit_learner(app, monolith)
install_v18364_ai_exit_pilot_guardian(app, monolith)
install_v18363_ai_exit_live_pilot(app, monolith)

__all__ = ["app"]
