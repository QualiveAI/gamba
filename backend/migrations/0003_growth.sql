CREATE TABLE IF NOT EXISTS growth_accounts (
    id BIGSERIAL PRIMARY KEY,
    platform TEXT NOT NULL,
    geo TEXT NOT NULL,
    proxy_id BIGINT,
    status TEXT NOT NULL DEFAULT 'warming',
    warmup_started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_post_at TIMESTAMPTZ,
    health_score INT NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS growth_proxies (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    country TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    last_checked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS growth_templates (
    id BIGSERIAL PRIMARY KEY,
    platform TEXT NOT NULL,
    geo TEXT NOT NULL,
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    media_ref TEXT,
    cta_link TEXT
);

CREATE TABLE IF NOT EXISTS growth_posts (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES growth_accounts(id) ON DELETE RESTRICT,
    template_id BIGINT REFERENCES growth_templates(id) ON DELETE RESTRICT,
    posted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    platform_post_id TEXT,
    clicks INT NOT NULL DEFAULT 0,
    signups INT NOT NULL DEFAULT 0
);