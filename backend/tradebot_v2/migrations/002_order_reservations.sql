CREATE TABLE IF NOT EXISTS tradebot_v2_order_reservations (
  request_id TEXT PRIMARY KEY,
  client_order_id TEXT NOT NULL UNIQUE,
  symbol TEXT NOT NULL CHECK (symbol IN ('AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOG', 'GOOGL', 'META')),
  side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
  quantity NUMERIC NOT NULL CHECK (quantity > 0),
  status TEXT NOT NULL DEFAULT 'reserved' CHECK (status IN (
    'reserved', 'submitted_unknown', 'accepted', 'partially_filled',
    'filled', 'rejected', 'cancelled'
  )),
  cumulative_filled NUMERIC NOT NULL DEFAULT 0 CHECK (
    cumulative_filled >= 0 AND cumulative_filled <= quantity
  ),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS tradebot_v2_one_active_order_per_symbol
ON tradebot_v2_order_reservations (symbol)
WHERE status IN ('reserved', 'submitted_unknown', 'accepted', 'partially_filled');
