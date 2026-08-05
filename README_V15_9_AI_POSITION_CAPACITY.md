# V15.9 AI Position Capacity

This release removes the legacy fixed one-position limit from live trading.

## Behaviour

- The manual position slider is informational while AI capacity is enabled.
- Effective capacity follows the AI-promoted target position size and available capital.
- A 10% target allocation can permit up to ten concurrent positions.
- A 20% target allocation can permit up to five concurrent positions.
- The bot never fills slots merely because they exist. Every position must still pass all existing quality, spread, confidence, risk, PDT, duplicate-symbol and cash checks.
- New positions remain limited to one per scan loop, preventing a burst of simultaneous orders.
- Immutable hard safety ceiling defaults to 10 and can be reduced with AI_POSITION_HARD_CAP.
- The AI Operator can alter position sizing; effective position capacity adjusts automatically from that sizing.

## Verification endpoint

GET /ai-position-capacity

Returns configured legacy value, effective live capacity, hard ceiling, open positions, available slots and the reason for the current capacity.

No entry gates, exits, stop losses, order submission or PDT protections were removed.
