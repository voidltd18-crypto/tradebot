
# --- HARD STOP LOSS PATCH ---

FAST_STOP_LOSS_PCT = -1.2

def check_hard_stop(symbol, pnl_pct):
    # 🚨 HARD STOP LOSS (ALWAYS FIRST)
    if pnl_pct <= FAST_STOP_LOSS_PCT:
        print(f"FAST STOP LOSS SELL {symbol} {pnl_pct:.2f}%")
        try:
            sell_position(symbol)
        except Exception as e:
            print(f"Stop loss sell error: {e}")
        return True
    return False
