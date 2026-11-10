-- Isolated experimental schema for TradeBot stock sell recovery.
-- Apply ONLY to a dedicated test database/branch after review.
-- Do not automatically run this migration on production Render startup.
CREATE TABLE IF NOT EXISTS tradebot_stock_sell_recovery_v1 (
  symbol TEXT NOT NULL,
  position_key TEXT NOT NULL,
  attempt_id TEXT NOT NULL UNIQUE,
  intended_qty NUMERIC(24, 8) NOT NULL CHECK (intended_qty > 0),
  broker_order_id TEXT,
  status TEXT NOT NULL CHECK (status IN (
    'RESERVED','UNKNOWN','ACKNOWLEDGED','WORKING','PARTIAL',
    'TERMINAL_AWAIT_POSITION','VERIFIED_FLAT'
  )),
  filled_qty NUMERIC(24, 8) NOT NULL DEFAULT 0 CHECK (filled_qty >= 0),
  PRIMARY KEY (symbol, position_key)
);
CREATE UNIQUE INDEX IF NOT EXISTS tradebot_stock_sell_order_id_v1
  ON tradebot_stock_sell_recovery_v1 (broker_order_id)
  WHERE broker_order_id IS NOT NULL;
