
from fastapi import FastAPI
app = FastAPI()

AUTO_UNIVERSE_SIZE = 20
MAX_POSITIONS = 20

PHASE2_MIN_CONFIDENCE = 0.75
PHASE2_MIN_QUALITY = 0.04
PHASE2_MAX_SPREAD = 0.0025

@app.get("/")
def root():
    return {"status": "Phase 2 bot running", "universe": AUTO_UNIVERSE_SIZE}

@app.get("/phase2")
def phase2():
    return {
        "enabled": True,
        "universeSize": AUTO_UNIVERSE_SIZE,
        "maxPositions": MAX_POSITIONS,
        "minConfidence": PHASE2_MIN_CONFIDENCE,
        "minQuality": PHASE2_MIN_QUALITY
    }
