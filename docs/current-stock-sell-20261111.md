# Current-main stock sell safety hotfix (11 November 2026)

This small, reviewable branch starts from the production main commit
`d0d5d1608cf192bd9de8f4439ce967d45a557582`.
It is independent of the 118-commit experimental recovery PR #186.

## Verified current source behaviour

The AST-only source audit confirms:
- `market_sell_qty()` submits the order before attempting to persist
  `pending_sell_orders`.
- `register_pending_sell_order()` returns `False` for a database
  persistence error.
- Before this hotfix, the caller logged a warning and continued.
  A broker acknowledgement is *not* a fill, and realised accounting
  still awaits broker reconciliation.

## Narrow safe correction

When an accepted order's pending-record insertion fails, the legacy
sell function now sends an urgent notice containing the symbol and
broker order ID and warns against automatic retry. The error path
does not submit an extra order, fake a fill, modify the broker order,
or change normal successful sell submission behaviour.

AST-extracted tests execute the real function against a fake client to
verify exactly one broker submission and the new failure alert. The
test workflow imports no live monolith and uses no brokerage credentials.

## Remaining risk

**This is an alerting safety hotfix, not a durable execution journal.**
The accepted-but-untracked broker order could still become ambiguous
after process restart. It does not resolve the underlying
pre-submission durable reservation and broker idempotency gap.
Keep PR #186 experimental and perform separate verified integration
and paper execution tests before replacing the sell execution path.

No live orders, Render settings or deployments were changed by this PR.
