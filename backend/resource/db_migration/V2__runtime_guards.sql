CREATE TABLE auth_limits (
    bucket varchar(128) PRIMARY KEY,
    failures integer NOT NULL DEFAULT 0,
    reset_at timestamptz NOT NULL
);
CREATE INDEX auth_limits_reset_idx ON auth_limits(reset_at);

ALTER TABLE outgoing_sms ADD COLUMN delivered_at timestamptz;
ALTER TABLE devices ADD COLUMN iccid varchar(32);
ALTER TABLE devices ADD COLUMN enabled boolean NOT NULL DEFAULT true;
ALTER TABLE devices ADD COLUMN queue_depth integer NOT NULL DEFAULT 0;
ALTER TABLE send_attempts ADD COLUMN result_fingerprint text;
