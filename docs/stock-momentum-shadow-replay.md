# Stock momentum shadow replay (experimental)

This branch adds a **read-only, authenticated** API preview, not an automatic
background worker. It does not connect to a live Alpaca data stream or place
orders. All observations must be supplied by an authorised caller. No feature
flag is enabled on the production trading engine.

POST `/v19/stock-momentum-replay` with the usual TradeBot API credentials:

```json
{
  "entryPrice": 100,
  "observations": [
    {"timestamp": "2026-11-10T14:30:00Z", "price": 100},
    {"timestamp": "2026-11-10T14:30:10Z", "price": 100.3},
    {"timestamp": "2026-11-10T14:30:20Z", "price": 101},
    {"timestamp": "2026-11-10T14:30:30Z", "price": 102},
    {"timestamp": "2026-11-10T14:30:40Z", "price": 103},
    {"timestamp": "2026-11-10T14:30:50Z", "price": 102.4},
    {"timestamp": "2026-11-10T14:31:00Z", "price": 102.2}
  ]
}
```

Output includes first hypothetical sample-price exits using 0.5% spike / 0.7%
trend trailing giveback, compared against a fixed 0.7% reference baseline.
Activation needs a 2% peak gain and adequate recent data. Spike momentum needs
a 1.5% rise over five consecutive observations. A gap over 120 seconds
clears momentum state, without losing the historical high watermark.

**Limitations:** Results assume instantaneous execution at the observed sample
price, before spread, slippage, fees and tax. No PDT / broker / order-state
simulation, no historical FMC replay, no live market ingestion, no persistence
across processes or sessions. These results are NOT proof of positive returns.
A permanent live rollout requires data timestamps and sampling validation,
position-specific state persistence, reconciliation of existing sell rules,
market-hours tests, paper-trading evidence, and explicit review.

Related: draft PR #186; this remains separate from the original selling rules.
