"""TradeBot FastAPI entry point.

V12.2 begins the safe modular migration without changing live behaviour.
The proven V12.1 application remains intact in ``backend.legacy.monolith``
while new services are extracted incrementally behind stable interfaces.

Render command remains:
    uvicorn backend.main:app --host 0.0.0.0 --port $PORT
"""
from backend.legacy.monolith import app

__all__ = ["app"]
