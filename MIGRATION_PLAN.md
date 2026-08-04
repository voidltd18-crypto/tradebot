# Extraction order

1. CEO and Board read-only services/routes.
2. Memory/database helpers and shared models.
3. Research and reputation services.
4. Evolution and risk orchestration.
5. Execution last, after parity tests, because it can place live orders.

Every extraction keeps the same endpoint contracts and includes a fallback to
the legacy implementation until output parity is confirmed.
