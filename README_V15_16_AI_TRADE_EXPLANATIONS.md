# V15.16 AI Trade Explanations

Adds truthful per-buy sizing explanations. Every new buy records:
- final USD/GBP allocation
- percentage of managed capital
- confidence and confidence multiplier
- quality score and spread
- AI Risk Engine multiplier and rationale
- constitutional cap and cash reserve
- approving gates

Explanations persist in `/var/data/trade_explanations.json` (or PERSISTENT_DATA_DIR) independently from SQLite. Existing positions receive a clearly labelled reconstructed summary.

Endpoint: `GET /trade-explanations` or `GET /trade-explanations?symbol=GOOG`.
