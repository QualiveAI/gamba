-- 0015_demo_catalog.sql
-- Каталог из WINDROP-демо: обложки/картинки/тиры + сессии «Ракетки» и «Копосов»
ALTER TABLE cases ADD COLUMN IF NOT EXISTS cover TEXT;
ALTER TABLE case_rewards ADD COLUMN IF NOT EXISTS image TEXT;
ALTER TABLE case_rewards ADD COLUMN IF NOT EXISTS rarity TEXT;
ALTER TABLE user_items ADD COLUMN IF NOT EXISTS image TEXT;

CREATE TABLE IF NOT EXISTS crash_sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    bet_units BIGINT NOT NULL CHECK (bet_units > 0),
    crash_point NUMERIC(14,2) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','cashed','busted')),
    cashout_multiplier NUMERIC(14,2),
    payout_units BIGINT,
    ended_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_crash_sessions_user_status ON crash_sessions(user_id, status);

CREATE TABLE IF NOT EXISTS shell_sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    bet_units BIGINT NOT NULL CHECK (bet_units > 0),
    cups INT NOT NULL CHECK (cups BETWEEN 3 AND 5),
    ball INT NOT NULL CHECK (ball >= 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','done')),
    guess INT,
    win BOOLEAN,
    payout_units BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_shell_sessions_user_status ON shell_sessions(user_id, status);
