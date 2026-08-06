TradeBot V16.7.2 - Minimum Meaningful Allocation Guard

Replace:
  backend/legacy/monolith.py

Default behaviour:
- AI portfolio allocations below $10 are not submitted.
- Tiny residual buying power remains as cash.
- The guard runs during planning and again immediately before order submission.
- All V16.7.1 buy, adaptive exit, rotation, PDT, quality and reliability protections remain included.

Optional Render environment variable:
  AI_PORTFOLIO_MIN_ALLOCATION_USD=10

You can later raise this to 15 or 20 without another code deployment.
