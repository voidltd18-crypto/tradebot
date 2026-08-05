# V15.10 True AI Position Capacity

This release removes the final legacy affordability cap from the portfolio's maximum position count.

- Effective capacity is derived from the AI target allocation and immutable hard safety cap.
- Current buying power controls how many additional positions can be funded now, not the strategic maximum capacity.
- The old saved `maxPositions=1` remains visible only as legacy configuration and no longer restricts autonomous capacity.
- A 10% target allocation permits 10 concurrent positions (subject to the hard cap).
- Each extra position must still pass all existing signal, confidence, quality, spread, PDT, symbol, cash and risk checks.
- Existing oversized legacy positions are not automatically sold or resized.

Diagnostic endpoint: `GET /ai-position-capacity`
