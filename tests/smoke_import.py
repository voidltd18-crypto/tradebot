"""Import smoke test used before deployment."""
from backend.main import app

assert app is not None
assert getattr(app, "routes", None)
print(f"OK: FastAPI app imported with {len(app.routes)} routes")
