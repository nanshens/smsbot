ALTER TABLE sim_cards
    ADD COLUMN offline_channel_id uuid REFERENCES notification_channels(id) ON DELETE SET NULL,
    ADD COLUMN offline_after_hours integer NOT NULL DEFAULT 1 CHECK (offline_after_hours BETWEEN 1 AND 720),
    ADD COLUMN offline_alert_generation integer NOT NULL DEFAULT 0;

CREATE TABLE device_offline_notifications (
    id uuid PRIMARY KEY,
    sim_id uuid NOT NULL REFERENCES sim_cards(id) ON DELETE CASCADE,
    device_id uuid NOT NULL REFERENCES devices(id),
    channel_id uuid NOT NULL REFERENCES notification_channels(id),
    offline_since timestamptz NOT NULL,
    generation integer NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'sent', 'cancelled')),
    attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    lease_token uuid,
    lease_expires_at timestamptz,
    last_error text,
    sent_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (sim_id, offline_since, generation)
);
CREATE INDEX device_offline_notifications_pending_idx
    ON device_offline_notifications(next_attempt_at) WHERE status = 'pending';
