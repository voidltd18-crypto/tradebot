# V19 Universal crypto dip-cycle — staged rollout

This change is **not live by default**. It adds a universal, explicitly approved
post-sale dip re-buy worker for Alpaca-supported USD crypto pairs. The initial
position is still opened manually. A buy cycle only arms after a broker-confirmed
filled profit-sell order from TradeBot (client order prefix `tbprofit-`).

## First: verify manual sells on paper
The shared `/sell/{symbol}` path now uses Alpaca's asset class: crypto markets
submit GTC market sells; stock DAY remains unchanged. Confirm the broker
accepted and **filled** the order, not simply acknowledged submission. Never
repeatedly press sell when broker status is unknown; inspect open orders first.

## Existing profit seller (independent feature)
Requires explicit settings:
- `TRADEBOT_CRYPTO_PROFIT_SELL_ENABLED=true`
- `TRADEBOT_CRYPTO_PROFIT_SELL_LIVE_APPROVED=true`
- `TRADEBOT_CRYPTO_PROFIT_SELL_SYMBOLS=UNIUSD,XRPUSD,...`
- `TRADEBOT_CRYPTO_PROFIT_SELL_MIN_GAIN_PCT` and cost-buffer settings as supported.

This is a **profit-only limit sell**; there is no guaranteed exit, no
guaranteed net profit, and no automatic loss stop. Existing pending GTC
limit orders can prevent manual sells until cancelled/reconciled.

## Universal post-sale re-buy (independent feature)
- `TRADEBOT_UNIVERSAL_CRYPTO_CYCLE_ENABLED=true`
- `TRADEBOT_UNIVERSAL_CRYPTO_CYCLE_LIVE_APPROVED=true`
- `TRADEBOT_UNIVERSAL_CRYPTO_CYCLE_SYMBOLS=UNIUSD,XRPUSD,...`
- `TRADEBOT_UNIVERSAL_CRYPTO_CYCLE_SPEND_USD=100` (or `ALL`, after review)
- `TRADEBOT_UNIVERSAL_CRYPTO_CYCLE_PULLBACK_PCT=0.5`

Rules: a verified `tbprofit-` filled sale of *that specific coin*, a fresh
ask, at least 30 minutes since fill, a dip >= configured threshold, no
holding or pending order for the pair, verified buying power and a single
reserved buy attempt per sale. Limit buys use GTC. The worker is disabled
unless both environment switches are true. Do not simultaneously enable the
old XRP worker for XRP; universal XRP is suppressed when the old worker
is configured enabled.

IMPORTANT: do not enable both workers for live funds without a separate
paper-trading test and deployment audit. Different crypto pairs may compete
for the same cash; the broker makes the final available-funds decision.
Dip buying after a sale does not guarantee a profitable future exit.
