-- Новые платежи изолированы от неоднозначных legacy amount_minor/balance_units.
-- Миграция не конвертирует и не исправляет существующие пользовательские остатки.

CREATE TABLE payment_quotes (
    id TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    tenant TEXT NOT NULL,
    coins BIGINT NOT NULL CHECK (coins > 0),
    amount_brl_minor BIGINT NOT NULL CHECK (amount_brl_minor > 0),
    fee_brl_minor BIGINT NOT NULL CHECK (fee_brl_minor >= 0),
    gross_brl_minor BIGINT NOT NULL CHECK (gross_brl_minor > 0),
    net_brl_minor BIGINT NOT NULL CHECK (net_brl_minor > 0),
    coin_usd_price NUMERIC(38,18) NOT NULL CHECK (coin_usd_price > 0),
    usd_brl_rate NUMERIC(38,18) NOT NULL CHECK (usd_brl_rate > 0),
    fee_percent NUMERIC(38,18) NOT NULL CHECK (fee_percent BETWEEN 0 AND 100),
    rate_version TEXT NOT NULL,
    config_version TEXT NOT NULL,
    config_snapshot JSONB NOT NULL,
    method TEXT NOT NULL CHECK (method IN ('stars','gift','card','crypto')),
    rail TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('sandbox','live')),
    channel TEXT NOT NULL CHECK (channel IN ('telegram','web')),
    provider_amount_atomic BIGINT NOT NULL CHECK (provider_amount_atomic > 0),
    provider_currency TEXT NOT NULL,
    provider_exponent INTEGER NOT NULL CHECK (provider_exponent BETWEEN 0 AND 18),
    chain TEXT,
    token TEXT,
    address TEXT,
    merchant_bot_id BIGINT,
    auth_bot_id BIGINT,
    auth_scope TEXT NOT NULL CHECK (auth_scope IN ('primary','managed','guest','roblox')),
    is_guest BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    CHECK (gross_brl_minor = net_brl_minor + fee_brl_minor),
    CHECK (amount_brl_minor = net_brl_minor),
    CHECK (expires_at > created_at),
    CHECK (NOT is_guest OR mode = 'sandbox'),
    CHECK (method <> 'crypto' OR (chain IS NOT NULL AND token IS NOT NULL AND address IS NOT NULL))
);
CREATE INDEX idx_payment_quotes_owner ON payment_quotes(user_id, created_at);

CREATE FUNCTION payment_quote_immutable() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'payment_quote_immutable';
END;
$$;
CREATE TRIGGER payment_quote_immutable BEFORE UPDATE OR DELETE ON payment_quotes
    FOR EACH ROW EXECUTE FUNCTION payment_quote_immutable();

ALTER TABLE payment_intents DROP CONSTRAINT payment_intents_idempotency_key_key;
ALTER TABLE payment_intents DROP CONSTRAINT payment_intents_status_check;
ALTER TABLE payment_intents ADD CONSTRAINT payment_intents_status_check
    CHECK (status IN ('pending','succeeded','sandbox_succeeded','failed','expired','refunded'));
ALTER TABLE payment_intents
    ADD COLUMN quote_id TEXT UNIQUE REFERENCES payment_quotes(id) ON DELETE RESTRICT,
    ADD COLUMN coins BIGINT CHECK (coins > 0),
    ADD COLUMN method TEXT CHECK (method IN ('stars','gift','card','crypto')),
    ADD COLUMN mode TEXT NOT NULL DEFAULT 'disabled' CHECK (mode IN ('disabled','sandbox','live')),
    ADD COLUMN wallet_unit TEXT,
    ADD COLUMN config_version TEXT,
    ADD COLUMN payload_hash TEXT,
    ADD COLUMN provider_amount_atomic BIGINT CHECK (provider_amount_atomic > 0),
    ADD COLUMN provider_currency TEXT,
    ADD COLUMN provider_exponent INTEGER CHECK (provider_exponent BETWEEN 0 AND 18),
    ADD COLUMN chain TEXT,
    ADD COLUMN token TEXT,
    ADD COLUMN address TEXT,
    ADD COLUMN merchant_bot_id BIGINT,
    ADD COLUMN expires_at TIMESTAMPTZ,
    ADD COLUMN client_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN charge_id TEXT,
    ADD COLUMN refund_status TEXT NOT NULL DEFAULT 'none'
        CHECK (refund_status IN ('none','requested','processing','failed','unknown','refunded')),
    ADD COLUMN refund_requested_by BIGINT REFERENCES users(id) ON DELETE RESTRICT,
    ADD COLUMN refund_requested_at TIMESTAMPTZ,
    ADD COLUMN refund_error TEXT,
    ADD COLUMN refunded_at TIMESTAMPTZ;
CREATE UNIQUE INDEX idx_payment_intents_owner_key ON payment_intents(user_id, idempotency_key);
CREATE UNIQUE INDEX idx_payment_intents_provider_ref ON payment_intents(rail, mode, provider_ref)
    WHERE quote_id IS NOT NULL AND provider_ref IS NOT NULL;
CREATE UNIQUE INDEX idx_payment_intents_charge ON payment_intents(rail, mode, charge_id)
    WHERE charge_id IS NOT NULL;
ALTER TABLE payment_intents ADD CONSTRAINT payment_intents_safe_fields CHECK (
    quote_id IS NULL OR (
        coins IS NOT NULL AND method IS NOT NULL AND wallet_unit = 'coin'
        AND mode IN ('sandbox','live') AND payload_hash IS NOT NULL
        AND provider_amount_atomic IS NOT NULL AND provider_currency IS NOT NULL
        AND provider_exponent IS NOT NULL AND expires_at IS NOT NULL
        AND config_version IS NOT NULL
        AND amount_minor = provider_amount_atomic AND currency = provider_currency
    )
);

CREATE FUNCTION payment_intent_immutable() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.quote_id IS NULL AND NEW.quote_id IS NOT NULL THEN
        RAISE EXCEPTION 'legacy_payment_requires_review';
    END IF;
    IF OLD.quote_id IS NOT NULL AND
       (to_jsonb(OLD) - ARRAY['status','provider_ref','client_payload','settled_at','charge_id',
        'refund_status','refund_requested_by','refund_requested_at','refund_error','refunded_at'])
       IS DISTINCT FROM
       (to_jsonb(NEW) - ARRAY['status','provider_ref','client_payload','settled_at','charge_id',
        'refund_status','refund_requested_by','refund_requested_at','refund_error','refunded_at']) THEN
        RAISE EXCEPTION 'payment_intent_terms_immutable';
    END IF;
    IF OLD.provider_ref IS NOT NULL AND OLD.provider_ref IS DISTINCT FROM NEW.provider_ref THEN
        RAISE EXCEPTION 'payment_provider_ref_immutable';
    END IF;
    IF OLD.charge_id IS NOT NULL AND OLD.charge_id IS DISTINCT FROM NEW.charge_id THEN
        RAISE EXCEPTION 'payment_charge_immutable';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER payment_intent_immutable BEFORE UPDATE ON payment_intents
    FOR EACH ROW EXECUTE FUNCTION payment_intent_immutable();

ALTER TABLE payment_events DROP CONSTRAINT payment_events_rail_provider_event_id_key;
ALTER TABLE payment_events
    ADD COLUMN mode TEXT NOT NULL DEFAULT 'disabled' CHECK (mode IN ('disabled','sandbox','live')),
    ADD COLUMN reference_id TEXT,
    ADD COLUMN event_kind TEXT NOT NULL DEFAULT 'payment'
        CHECK (event_kind IN ('payment','gift_receipt','gift_request','refund')),
    ADD COLUMN raw_body BYTEA,
    ADD COLUMN payload_hash TEXT,
    ADD COLUMN authenticated BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN verification_source TEXT,
    ADD COLUMN verification_state TEXT NOT NULL DEFAULT 'unverified'
        CHECK (verification_state IN ('unverified','authenticated','verified','rejected')),
    ADD COLUMN verified_payload JSONB,
    ADD COLUMN verification_error TEXT,
    ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE UNIQUE INDEX idx_payment_events_rail_mode_key
    ON payment_events(rail, mode, provider_event_id);
CREATE INDEX idx_payment_events_reference ON payment_events(reference_id);

-- Один ref на intent независимо от числа callback/event_id и гонок poll/worker.
-- Существующий индекс ledger(user_id,currency,ref_id) сохраняется без изменений.
CREATE UNIQUE INDEX idx_ledger_deposit_intent_ref ON ledger_entries(ref_id)
    WHERE reason = 'deposit_units' AND ref_id LIKE 'deposit:%';

-- Выключатели отсутствуют => закрыто; ранее установленное значение сохраняется.
INSERT INTO system_config (key, value) VALUES
    ('deposits_enabled', '{"value":false}'),
    ('payments_stars_enabled', '{"value":false}'),
    ('payments_gift_enabled', '{"value":false}'),
    ('payments_card_enabled', '{"value":false}'),
    ('payments_crypto_enabled', '{"value":false}'),
    ('payments_stars_refunds_enabled', '{"value":false}')
ON CONFLICT (key) DO NOTHING;
