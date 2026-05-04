import time

latest_status = {}

def touch_quick_status():
    """Safely trigger status refresh without crashing"""
    try:
        global latest_status
        if isinstance(latest_status, dict):
            latest_status["last_update"] = time.time()
    except Exception:
        pass

def add_stock(symbol):
    # example logic
    if "touch_quick_status" in globals():
        touch_quick_status()
    return {"ok": True, "symbol": symbol}
