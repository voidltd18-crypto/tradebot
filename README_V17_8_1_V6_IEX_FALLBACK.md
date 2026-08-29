# TradeBot V17.8.1 — V6 Historical Data IEX Fallback

This patch fixes V6.5/V6.6 research outcomes that were stuck with Alpaca errors such as:

`subscription does not permit querying recent SIP data`

## Change

- V6 historical checkpoint lookup still attempts the existing Alpaca historical feed first.
- If Alpaca rejects recent SIP history because of subscription entitlement, V6 retries the same historical one-minute window using `DataFeed.IEX`.
- Once fallback is triggered for that checkpoint evaluation, later expanded windows use IEX directly.
- IEX historical checkpoint rows are accepted by the V6 source validator and by the legacy-outcome repair logic.
- Logs include `V17.8.1 V6 DATA FALLBACK | SYMBOL SIP historical unavailable -> IEX historical feed`.

## Safety scope

Research/outcome evaluation only. No live entry gates, order submission, exit logic, V17.7 adaptive trailing, Peak Exhaustion, Profit Vault, full-buy sizing, or Adaptive Universe logic was changed.
