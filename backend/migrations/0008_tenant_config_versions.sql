CREATE TABLE IF NOT EXISTS tenant_config_versions (
    id          BIGSERIAL PRIMARY KEY,
    tenant      TEXT NOT NULL,
    version     INTEGER NOT NULL,
    config      JSONB NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT FALSE,
    pinned      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    activated_at TIMESTAMPTZ,
    UNIQUE (tenant, version)
);
CREATE INDEX IF NOT EXISTS idx_tenant_config_versions_tenant ON tenant_config_versions(tenant);
CREATE INDEX IF NOT EXISTS idx_tenant_config_versions_active ON tenant_config_versions(tenant) WHERE is_active = TRUE;
