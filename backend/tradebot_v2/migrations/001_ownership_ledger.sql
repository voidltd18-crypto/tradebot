-- TradeBot 2.0 isolated ownership ledger.
-- Run only against a dedicated TradeBot 2.0 database.
-- This migration does not adopt any existing Alpaca holdings.
CREATE TABLE IF NOT EXISTS tradebot_v2_fill_events (
  event_id TEXT PRIMARY KEY,
  broker_order_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('BUY_FILLED','SELL_FILLED')),
  quantity NUMERIC(24,10) NOT NULL CHECK (quantity > 0),
  recorded_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (broker_order_id, kind, quantity, recorded_at)
);
CREATE INDEX IF NOT EXISTS tradebot_v2_fill_events_symbol_time
ON tradebot_v2_fill_events(symbol, recorded_at);
-- Append-only enforcement: records must never be changed after insertion.
CREATE OR REPLACE FUNCTION tradebot_v2_reject_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'TradeBot v2 fill ledger is append-only';
END;
$$;
DROP TRIGGER IF EXISTS tradebot_v2_no_update ON tradebot_v2_fill_events;
CREATE TRIGGER tradebot_v2_no_update BEFORE UPDATE OR DELETE
ON tradebot_v2_fill_events FOR EACH ROW EXECUTE FUNCTION tradebot_v2_reject_mutation();
