ALTER TABLE tradebot_v2_order_reservations
    ADD COLUMN IF NOT EXISTS account_id UUID,
    ADD COLUMN IF NOT EXISTS broker_order_id UUID,
    ADD COLUMN IF NOT EXISTS broker_updated_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS tradebot_v2_broker_order_identity
ON tradebot_v2_order_reservations (account_id, broker_order_id)
WHERE broker_order_id IS NOT NULL;

ALTER TABLE tradebot_v2_fill_events
    ADD COLUMN IF NOT EXISTS account_id UUID,
    ADD COLUMN IF NOT EXISTS reservation_id TEXT REFERENCES tradebot_v2_order_reservations(request_id);

-- Distinct executions can share a timestamp and quantity. Broker activity ID
-- (encoded in the primary key) is the identity used for recovered fills.
ALTER TABLE tradebot_v2_fill_events
    DROP CONSTRAINT IF EXISTS tradebot_v2_fill_events_broker_order_id_kind_quantity_recor_key;

CREATE UNIQUE INDEX IF NOT EXISTS tradebot_v2_legacy_fill_identity
ON tradebot_v2_fill_events (broker_order_id, kind, quantity, recorded_at)
WHERE account_id IS NULL;

CREATE INDEX IF NOT EXISTS tradebot_v2_fill_reservation
ON tradebot_v2_fill_events (reservation_id) WHERE reservation_id IS NOT NULL;
