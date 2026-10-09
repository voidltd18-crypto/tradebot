"""V18.3.76 Keep Buying After Daily Loss.

Disables only the legacy Profit Optimiser rule that pauses new stock buys
after the realised daily P&L drops below DAILY_LOSS_LIMIT_OPTIMIZER.

All normal entry gates, position limits, PDT controls, symbol locks,
blacklists, confidence/quality checks, buying-power checks, and sell logic
remain unchanged. The daily profit-target pause is also left unchanged.
"""

from __future__ import annotations


def install_v18376_keep_buying_after_loss(app, m) -> None:
    previous = bool(getattr(m, "PAUSE_BUYS_AFTER_DAILY_LOSS", True))
    m.PAUSE_BUYS_AFTER_DAILY_LOSS = False

    print(
        "V18.3.76 DAILY LOSS BUY PAUSE | installed "
        f"previous={previous} enabled={m.PAUSE_BUYS_AFTER_DAILY_LOSS} "
        "scope=STOCK_BUY_GUARDRAIL_ONLY"
    )
