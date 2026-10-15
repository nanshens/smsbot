-- A phone can exist before the hardware reports its ICCID.
ALTER TABLE sim_cards ALTER COLUMN iccid DROP NOT NULL;
-- Prevent multiple card rows (and thus multiple keys) for the same phone label.
CREATE UNIQUE INDEX sim_cards_phone_unique ON sim_cards
    ((regexp_replace(phone_number, '[^0-9]', '', 'g')))
    WHERE phone_number IS NOT NULL AND regexp_replace(phone_number, '[^0-9]', '', 'g') <> '';
