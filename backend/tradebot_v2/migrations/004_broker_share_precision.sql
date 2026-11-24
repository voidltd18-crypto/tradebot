-- Alpaca supports share quantities to nine decimal places.
ALTER TABLE tradebot_v2_order_reservations
    ALTER COLUMN quantity TYPE NUMERIC(25,9),
    ALTER COLUMN cumulative_filled TYPE NUMERIC(25,9);

ALTER TABLE tradebot_v2_fill_events
    ALTER COLUMN quantity TYPE NUMERIC(26,10);
