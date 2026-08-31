# V18.2.23 Pointer Trade Explorer

Fixes Account Value chart selection by making the chart wrapper itself translate pointer X position into the nearest real account-value observation. This does not depend on Recharts activePayload/click event internals.

Selected point card now previews the number of closed trades in the selected period and their symbols, then View trades applies the matching Closed Trade History filter.

No backend or trading-strategy changes.
