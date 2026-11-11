-- Изолированный реестр официальных Managed Bots; старый plaintext bot_pool не используется.
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_guest BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS bot_registry (
    bot_id BIGINT PRIMARY KEY CHECK (bot_id > 0),
    kind TEXT NOT NULL CHECK (kind IN ('main', 'managed')),
    username TEXT NOT NULL DEFAULT '',
    owner_telegram_id BIGINT,
    owner_user_id BIGINT REFERENCES users(id) ON DELETE RESTRICT,
    token_encrypted TEXT,
    token_fingerprint TEXT,
    credential_version BIGINT NOT NULL DEFAULT 1 CHECK (credential_version > 0),
    webhook_secret_encrypted TEXT NOT NULL,
    webhook_secret_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'revoked'
        CHECK (status IN ('provisioning', 'active', 'revoked')),
    last_manager_update_id BIGINT,
    manager_owner_changed BOOLEAN NOT NULL DEFAULT FALSE,
    pending_intent_id BIGINT,
    poll_offset BIGINT NOT NULL DEFAULT 0,
    health_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (health_status IN ('unknown', 'ok', 'degraded', 'auth_failed', 'revoked')),
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error_code TEXT,
    last_health_at TIMESTAMPTZ,
    next_health_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    alert_pending BOOLEAN NOT NULL DEFAULT FALSE,
    alert_attempts INTEGER NOT NULL DEFAULT 0,
    next_alert_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_alert_at TIMESTAMPTZ,
    last_alert_error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((kind = 'main' AND owner_telegram_id IS NULL AND owner_user_id IS NULL)
        OR (kind = 'managed' AND owner_telegram_id > 0))
);
CREATE UNIQUE INDEX IF NOT EXISTS bot_registry_one_main
    ON bot_registry(kind) WHERE kind = 'main';
CREATE INDEX IF NOT EXISTS bot_registry_owner
    ON bot_registry(owner_user_id) WHERE kind = 'managed';

CREATE TABLE IF NOT EXISTS bot_managed_intents (
    id BIGSERIAL PRIMARY KEY,
    request_id INTEGER NOT NULL,
    owner_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    owner_telegram_id BIGINT NOT NULL CHECK (owner_telegram_id > 0),
    bot_id BIGINT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'consumed', 'expired')),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT now() + interval '15 minutes',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS bot_managed_one_pending_intent
    ON bot_managed_intents(owner_telegram_id) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS bot_private_chats (
    bot_id BIGINT NOT NULL REFERENCES bot_registry(bot_id) ON DELETE RESTRICT,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    chat_id BIGINT NOT NULL CHECK (chat_id > 0),
    credential_version BIGINT NOT NULL CHECK (credential_version > 0),
    confirmed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (bot_id, user_id)
);

CREATE TABLE IF NOT EXISTS bot_inbox (
    id BIGSERIAL PRIMARY KEY,
    bot_id BIGINT NOT NULL REFERENCES bot_registry(bot_id) ON DELETE RESTRICT,
    update_id BIGINT NOT NULL CHECK (update_id >= 0),
    credential_version BIGINT NOT NULL CHECK (credential_version > 0),
    payload_encrypted TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'done', 'dead', 'dropped')),
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_until TIMESTAMPTZ,
    claim_token UUID,
    last_error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    UNIQUE (bot_id, update_id)
);
CREATE INDEX IF NOT EXISTS bot_inbox_ready ON bot_inbox(available_at, id)
    WHERE status IN ('pending', 'processing');

CREATE TABLE IF NOT EXISTS bot_outbox (
    id BIGSERIAL PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('deposit_confirmed', 'giftcard_delivery', 'bot_message')),
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    bot_id BIGINT REFERENCES bot_registry(bot_id) ON DELETE RESTRICT,
    payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    dedupe_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'done', 'dead', 'dropped')),
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_until TIMESTAMPTZ,
    claim_token UUID,
    last_error_code TEXT,
    telegram_message_id BIGINT,
    sent_bot_id BIGINT REFERENCES bot_registry(bot_id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS bot_outbox_ready ON bot_outbox(available_at, id)
    WHERE status IN ('pending', 'processing');

CREATE TABLE IF NOT EXISTS bot_user_attribution (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
    campaign TEXT NOT NULL CHECK (campaign IN ('organic', 'telegram', 'social', 'creator', 'launch-br')),
    source_bot_id BIGINT NOT NULL REFERENCES bot_registry(bot_id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
