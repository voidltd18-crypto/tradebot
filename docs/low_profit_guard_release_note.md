# Low-profit repeat-stock buy guard

The guard only filters **new buys and pre-sell rotations** when `TRADEBOT_LOW_PROFIT_BUY_GUARD_ENABLED=true`.

A symbol qualifies for exclusion only with at least three **distinct verified sell orders**, none earning more than £5 realised P&L. Trades without verified sell-order IDs and zero-share artefacts are excluded from the evidence. Missing data does not manufacture a blacklist.

This is not a minimum-profit sell target and cannot guarantee profitability. Existing positions and protective exits remain unchanged. Validate the live deployment commit and monitor rejections separately from realised returns.
