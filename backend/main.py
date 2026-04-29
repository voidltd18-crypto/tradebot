
# Aggressive Profit Taking Config
AGGRESSIVE_PROFIT_TAKING_ENABLED = True
AGGRESSIVE_TRAIL_START_PCT = 0.60
AGGRESSIVE_TRAIL_DISTANCE_PCT = 0.65
AGGRESSIVE_SMALL_PROFIT_TAKE_PCT = 1.20
AGGRESSIVE_EARLY_LOSS_CUT_PCT = -1.35

def aggressive_exit_decision(pnl_pct, minutes):
    if pnl_pct <= AGGRESSIVE_EARLY_LOSS_CUT_PCT and minutes > 8:
        return True, "EARLY LOSS CUT"
    if pnl_pct >= AGGRESSIVE_SMALL_PROFIT_TAKE_PCT and minutes > 12:
        return True, "TAKE PROFIT"
    return False, ""
