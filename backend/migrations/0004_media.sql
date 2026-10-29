CREATE TABLE IF NOT EXISTS media_assets (
    id BIGSERIAL PRIMARY KEY,
    owner_tenant TEXT NOT NULL DEFAULT 'default',
    kind TEXT NOT NULL DEFAULT 'image',
    storage_key TEXT NOT NULL,
    content_type TEXT NOT NULL,
    width INT,
    height INT,
    bytes BIGINT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    created_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);