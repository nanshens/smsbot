-- One manually issued external API key per SIM; plaintext is never stored.
CREATE TABLE sim_api_keys (
    sim_id uuid PRIMARY KEY REFERENCES sim_cards(id),
    key_hash text NOT NULL UNIQUE,
    key_hint varchar(20) NOT NULL,
    created_by uuid NOT NULL REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz
);
-- API idempotency survives key rotation, even when a different admin signs it.
CREATE UNIQUE INDEX outgoing_sms_api_idempotency_idx ON outgoing_sms(sim_id,idempotency_key)
    WHERE idempotency_key LIKE 'api:%';
