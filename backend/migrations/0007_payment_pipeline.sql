CREATE TABLE IF NOT EXISTS payment_intents (
    id              TEXT PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    tenant          TEXT NOT NULL,
    rail            TEXT NOT NULL,
    amount_minor    BIGINT NOT NULL CHECK (amount_minor > 0),
    currency        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','succeeded','failed','expired')),
    provider_ref    TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    settled_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_payment_intents_user ON payment_intents(user_id);
CREATE INDEX IF NOT EXISTS idx_payment_intents_status ON payment_intents(status);

CREATE TABLE IF NOT EXISTS payment_events (
    id                BIGSERIAL PRIMARY KEY,
    rail              TEXT NOT NULL,
    provider_event_id TEXT NOT NULL,
    intent_id         TEXT REFERENCES payment_intents(id) ON DELETE RESTRICT,
    raw_payload       JSONB NOT NULL,
    outcome           TEXT,
    received_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at      TIMESTAMPTZ,
    UNIQUE (rail, provider_event_id)
);
CREATE INDEX IF NOT EXISTS idx_payment_events_unprocessed
    ON payment_events(received_at) WHERE processed_at IS NULL;
