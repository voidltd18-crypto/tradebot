# V18.2.1 Working Capital Top Card

Restores Working Capital as a primary Command Center headline metric.

Top row order:
1. Equity
2. Working Capital
3. Today P&L
4. Total Gain/Loss
5. Profit Vault
6. Positions

Working Capital uses the Profit Vault adjusted `workingCapitalGbp` value when available, with broker buying power converted to GBP only as a fallback. No trading logic or backend behaviour changed.
