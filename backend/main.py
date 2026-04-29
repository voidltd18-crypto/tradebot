from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok", "message": "Elite bot running"}

@app.get("/status")
def status():
    return {
        "market": {"isOpen": True, "label": "OPEN"},
        "eliteMode": {"enabled": True}
    }
