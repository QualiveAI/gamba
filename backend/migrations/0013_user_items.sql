-- 0013: инвентарь — предметы, выпадающие из кейсов
CREATE TABLE IF NOT EXISTS user_items (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    game_key TEXT,
    currency TEXT NOT NULL DEFAULT 'units',
    value_coins INT NOT NULL,
    rarity TEXT NOT NULL DEFAULT 'Common',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_user_items_user ON user_items (user_id, status);
