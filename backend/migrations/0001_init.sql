CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE,
    roblox_user_id BIGINT UNIQUE,
    roblox_username TEXT,
    username TEXT,
    balance_units BIGINT NOT NULL DEFAULT 0 CHECK (balance_units >= 0),
    region TEXT,
    segment TEXT NOT NULL DEFAULT 'new' CHECK (segment IN ('new','active','veteran')),
    predictor_mode TEXT NOT NULL DEFAULT 'user' CHECK (predictor_mode IN ('user','admin')),
    rtp_profile TEXT NOT NULL DEFAULT 'standard',
    first_deposit_at TIMESTAMPTZ,
    last_claim_at TIMESTAMPTZ,
    device_fingerprint TEXT,
    signup_ip TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cases (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    price_units BIGINT NOT NULL CHECK (price_units >= 0),
    rtp_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS case_rewards (
    id BIGSERIAL PRIMARY KEY,
    case_id BIGINT NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    reward_type TEXT NOT NULL CHECK (reward_type IN ('balance','giftcard','game_topup')),
    game_key TEXT,
    nominal_units BIGINT NOT NULL CHECK (nominal_units >= 0),
    weight NUMERIC(12,6) NOT NULL CHECK (weight >= 0),
    region TEXT
);

CREATE TABLE IF NOT EXISTS case_openings (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    case_id BIGINT NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    reward_id BIGINT NOT NULL REFERENCES case_rewards(id) ON DELETE RESTRICT,
    server_seed TEXT NOT NULL,
    server_seed_hash TEXT NOT NULL,
    client_seed TEXT NOT NULL,
    nonce BIGINT NOT NULL,
    roll DOUBLE PRECISION NOT NULL,
    rtp_used DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gift_codes (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    region TEXT NOT NULL,
    nominal_units BIGINT NOT NULL CHECK (nominal_units >= 0),
    status TEXT NOT NULL DEFAULT 'available' CHECK (status IN ('available','reserved','issued','activated','expired')),
    reserved_by BIGINT REFERENCES users(id) ON DELETE RESTRICT,
    reserved_at TIMESTAMPTZ,
    issued_at TIMESTAMPTZ,
    activated_at TIMESTAMPTZ,
    verify_attempts INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS gift_conversions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    gift_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_review' CHECK (status IN ('pending_review','priced','credited')),
    price_rub NUMERIC(12,2),
    credited_units BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS withdrawals (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    amount_units BIGINT NOT NULL CHECK (amount_units >= 0),
    region TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','frozen','approved','rejected')),
    code_id BIGINT REFERENCES gift_codes(id) ON DELETE RESTRICT,
    fee_units BIGINT NOT NULL DEFAULT 0,
    antifraud_score TEXT,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at TIMESTAMPTZ,
    hold_until TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS withdrawal_freezes (
    id BIGSERIAL PRIMARY KEY,
    withdrawal_id BIGINT NOT NULL REFERENCES withdrawals(id) ON DELETE RESTRICT,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    unfrozen_at TIMESTAMPTZ,
    unfrozen_by BIGINT REFERENCES users(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ledger_entries (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    delta BIGINT NOT NULL,
    reason TEXT NOT NULL,
    ref_id TEXT,
    balance_after BIGINT NOT NULL CHECK (balance_after >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS referrals (
    id BIGSERIAL PRIMARY KEY,
    referrer_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    referee_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'held' CHECK (status IN ('held','released','denied')),
    bonus_released_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (referee_id)
);

CREATE TABLE IF NOT EXISTS referral_flags (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    reason TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS daily_rewards (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    claimed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    amount_units BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS deposit_streaks (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
    current_streak INT NOT NULL DEFAULT 0,
    last_deposit_date DATE,
    bonus_percent NUMERIC(5,4) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS missions (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    steps JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS mission_progress (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    mission_id BIGINT NOT NULL REFERENCES missions(id) ON DELETE RESTRICT,
    progress JSONB NOT NULL DEFAULT '{}'::jsonb,
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    reward_claimed BOOLEAN NOT NULL DEFAULT FALSE,
    day DATE NOT NULL,
    UNIQUE (user_id, mission_id, day)
);

CREATE TABLE IF NOT EXISTS mines_sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    bet_units BIGINT NOT NULL,
    mine_count INT NOT NULL,
    grid_size INT NOT NULL DEFAULT 25,
    mines JSONB NOT NULL,
    revealed JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','cashed_out','lost')),
    payout_units BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS mines_predictions (
    id BIGSERIAL PRIMARY KEY,
    session_id BIGINT NOT NULL REFERENCES mines_sessions(id) ON DELETE RESTRICT,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    suggested_cells JSONB NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    mode TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_subscriptions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    starts_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ends_at TIMESTAMPTZ NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    idempotency_key TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS antifraud_flags (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    rule TEXT NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payment_polling (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    amount_rub NUMERIC(12,2),
    amount_units BIGINT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','succeeded','failed','manual_review','completed')),
    receipt_url TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, external_id)
);

CREATE TABLE IF NOT EXISTS bot_pool (
    id BIGSERIAL PRIMARY KEY,
    token TEXT NOT NULL,
    name TEXT,
    warmup_until TIMESTAMPTZ,
    banned BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bot_health (
    id BIGSERIAL PRIMARY KEY,
    bot_token_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    details TEXT
);

CREATE TABLE IF NOT EXISTS analytics_daily (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL UNIQUE,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS system_config (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS win_feed (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    game TEXT NOT NULL,
    amount_units BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_events_type_created ON events(event_type, created_at);
CREATE INDEX IF NOT EXISTS idx_events_user_created ON events(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_payment_polling_status ON payment_polling(status);
CREATE INDEX IF NOT EXISTS idx_withdrawals_user_status ON withdrawals(user_id, status);
CREATE INDEX IF NOT EXISTS idx_gift_codes_status_region_nominal ON gift_codes(status, region, nominal_units);