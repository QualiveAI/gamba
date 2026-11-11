-- 0018: обмен целых монет на заранее закупленные gift cards.
-- Нет seed-данных, пересчёта балансов или переноса неоднозначных legacy-кодов.

CREATE TABLE IF NOT EXISTS giftcard_skus (
    id BIGSERIAL PRIMARY KEY,
    operator_sku TEXT NOT NULL UNIQUE CHECK (length(operator_sku) BETWEEN 1 AND 80),
    brand TEXT NOT NULL CHECK (brand = 'Roblox'),
    region TEXT NOT NULL CHECK (region = 'BR'),
    card_currency TEXT NOT NULL CHECK (card_currency = 'BRL'),
    face_value_minor BIGINT NOT NULL CHECK (face_value_minor BETWEEN 1 AND 9007199254740991),
    coin_cost BIGINT NOT NULL CHECK (coin_cost BETWEEN 1 AND 9007199254740991),
    sandbox BOOLEAN NOT NULL,
    active BOOLEAN NOT NULL DEFAULT FALSE,
    created_by BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS giftcard_batches (
    id BIGSERIAL PRIMARY KEY,
    sku_id BIGINT NOT NULL REFERENCES giftcard_skus(id) ON DELETE RESTRICT,
    supplier_name TEXT NOT NULL CHECK (length(supplier_name) BETWEEN 1 AND 120),
    batch_reference TEXT NOT NULL CHECK (length(batch_reference) BETWEEN 1 AND 160),
    provenance_reference TEXT NOT NULL CHECK (length(provenance_reference) BETWEEN 1 AND 240),
    distribution_agreement_reference TEXT CHECK (
        distribution_agreement_reference IS NULL
        OR length(distribution_agreement_reference) BETWEEN 1 AND 240
    ),
    imported_by BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    imported_count INTEGER NOT NULL CHECK (imported_count BETWEEN 1 AND 2000),
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (supplier_name, batch_reference),
    UNIQUE (id, sku_id)
);

CREATE TABLE IF NOT EXISTS giftcard_inventory (
    id BIGSERIAL PRIMARY KEY,
    sku_id BIGINT NOT NULL REFERENCES giftcard_skus(id) ON DELETE RESTRICT,
    batch_id BIGINT NOT NULL,
    code_ciphertext TEXT NOT NULL CHECK (length(code_ciphertext) BETWEEN 80 AND 2048),
    code_fingerprint TEXT NOT NULL UNIQUE CHECK (code_fingerprint ~ '^[0-9a-f]{64}$'),
    crypto_version SMALLINT NOT NULL DEFAULT 1 CHECK (crypto_version = 1),
    status TEXT NOT NULL DEFAULT 'available'
        CHECK (status IN ('available', 'assigned', 'issued', 'quarantined')),
    assigned_redemption_id BIGINT,
    assigned_at TIMESTAMPTZ,
    issued_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (batch_id, sku_id) REFERENCES giftcard_batches(id, sku_id) ON DELETE RESTRICT,
    UNIQUE (id, sku_id),
    CHECK (
        (status = 'available' AND assigned_redemption_id IS NULL AND assigned_at IS NULL AND issued_at IS NULL)
        OR (status IN ('assigned', 'issued') AND assigned_redemption_id IS NOT NULL AND assigned_at IS NOT NULL)
        OR status = 'quarantined'
    )
);

CREATE TABLE IF NOT EXISTS giftcard_redemptions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    telegram_id BIGINT NOT NULL CHECK (telegram_id > 0),
    sku_id BIGINT NOT NULL REFERENCES giftcard_skus(id) ON DELETE RESTRICT,
    inventory_id BIGINT NOT NULL,
    idempotency_key TEXT NOT NULL CHECK (idempotency_key ~ '^[A-Za-z0-9._:-]{1,128}$'),
    operator_sku TEXT NOT NULL,
    brand TEXT NOT NULL CHECK (brand = 'Roblox'),
    region TEXT NOT NULL CHECK (region = 'BR'),
    card_currency TEXT NOT NULL CHECK (card_currency = 'BRL'),
    face_value_minor BIGINT NOT NULL CHECK (face_value_minor BETWEEN 1 AND 9007199254740991),
    coin_cost BIGINT NOT NULL CHECK (coin_cost BETWEEN 1 AND 9007199254740991),
    sandbox BOOLEAN NOT NULL,
    auth_scope TEXT NOT NULL CHECK (auth_scope IN ('primary', 'managed')),
    bot_id BIGINT REFERENCES bot_registry(bot_id) ON DELETE RESTRICT CHECK (bot_id > 0),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'delivering', 'issued', 'rejected', 'manual_review')),
    delivery_started_at TIMESTAMPTZ,
    delivery_attempts INTEGER NOT NULL DEFAULT 0 CHECK (delivery_attempts >= 0),
    telegram_message_id BIGINT CHECK (telegram_message_id > 0),
    delivered_bot_id BIGINT REFERENCES bot_registry(bot_id) ON DELETE RESTRICT CHECK (delivered_bot_id > 0),
    delivered_credential_version BIGINT CHECK (delivered_credential_version > 0),
    delivered_at TIMESTAMPTZ,
    refunded_at TIMESTAMPTZ,
    rejection_reason TEXT CHECK (
        rejection_reason IN ('operator_rejected', 'requested_by_owner', 'risk_review')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, idempotency_key),
    UNIQUE (inventory_id, id),
    FOREIGN KEY (inventory_id, sku_id) REFERENCES giftcard_inventory(id, sku_id) ON DELETE RESTRICT,
    CHECK (auth_scope <> 'managed' OR bot_id IS NOT NULL),
    CHECK (status <> 'pending' OR delivery_started_at IS NULL),
    CHECK (status <> 'delivering' OR delivery_started_at IS NOT NULL),
    CHECK (
        status <> 'issued'
        OR (delivery_started_at IS NOT NULL AND delivered_at IS NOT NULL
            AND telegram_message_id IS NOT NULL AND delivered_bot_id IS NOT NULL
            AND delivered_credential_version IS NOT NULL)
    ),
    CHECK (
        (status = 'rejected' AND refunded_at IS NOT NULL AND delivery_started_at IS NULL AND delivered_at IS NULL)
        OR (status <> 'rejected' AND refunded_at IS NULL)
    )
);

-- После подтверждённого отказа до отправки код можно снова резервировать.
-- Отменённый заказ навсегда сохраняет свой inventory_id и никогда не доставляется.
CREATE UNIQUE INDEX IF NOT EXISTS idx_giftcard_single_assignment
    ON giftcard_redemptions(inventory_id) WHERE status <> 'rejected';
CREATE INDEX IF NOT EXISTS idx_giftcard_available_sku
    ON giftcard_inventory(sku_id, id) WHERE status = 'available';
CREATE INDEX IF NOT EXISTS idx_giftcard_redemptions_owner
    ON giftcard_redemptions(user_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_giftcard_redemptions_status
    ON giftcard_redemptions(status, id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'giftcard_inventory_assignment_fk'
          AND conrelid = 'giftcard_inventory'::regclass
    ) THEN
        ALTER TABLE giftcard_inventory ADD CONSTRAINT giftcard_inventory_assignment_fk
            FOREIGN KEY (id, assigned_redemption_id)
            REFERENCES giftcard_redemptions(inventory_id, id) ON DELETE RESTRICT;
    END IF;
END;
$$;

COMMENT ON TABLE giftcard_skus IS
    'Только явный mapping оператора: цена в целых ledger units, номинал карты отдельно в BRL minor.';
COMMENT ON TABLE giftcard_inventory IS
    'Только Fernet ciphertext и keyed HMAC fingerprint; legacy gift_codes не используются.';
COMMENT ON COLUMN giftcard_redemptions.delivery_started_at IS
    'После commit этого маркера возможна неоднозначная доставка; автоматический возврат запрещён.';
