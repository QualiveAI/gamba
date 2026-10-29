CREATE TABLE IF NOT EXISTS case_definitions (
    id BIGSERIAL PRIMARY KEY,
    tenant TEXT NOT NULL DEFAULT 'default',
    game_key TEXT NOT NULL,
    slug TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    artwork_media_id BIGINT REFERENCES media_assets(id) ON DELETE RESTRICT,
    currency TEXT NOT NULL CHECK (currency IN ('units','freebets')),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','archived')),
    created_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant, game_key, slug)
);

CREATE TABLE IF NOT EXISTS case_versions (
    id BIGSERIAL PRIMARY KEY,
    case_id BIGINT NOT NULL REFERENCES case_definitions(id) ON DELETE RESTRICT,
    version_no INT NOT NULL,
    rtp_target_bp INT NOT NULL,
    published_by BIGINT,
    published_at TIMESTAMPTZ,
    changelog TEXT,
    UNIQUE (case_id, version_no)
);

CREATE TABLE IF NOT EXISTS case_prizes (
    id BIGSERIAL PRIMARY KEY,
    version_id BIGINT NOT NULL REFERENCES case_versions(id) ON DELETE RESTRICT,
    sort_order INT NOT NULL DEFAULT 0,
    label TEXT NOT NULL,
    media_id BIGINT REFERENCES media_assets(id) ON DELETE RESTRICT,
    nominal_units BIGINT NOT NULL CHECK (nominal_units > 0),
    real_value_minor BIGINT NOT NULL DEFAULT 0 CHECK (real_value_minor >= 0),
    weight_bp INT NOT NULL CHECK (weight_bp >= 0)
);

ALTER TABLE case_openings ADD COLUMN IF NOT EXISTS catalog_version_id BIGINT REFERENCES case_versions(id) ON DELETE RESTRICT;

-- trigger to block updates/deletes after publish
CREATE OR REPLACE FUNCTION block_published_case_versions() RETURNS trigger AS $$
BEGIN
    IF OLD.published_at IS NOT NULL THEN
        RAISE EXCEPTION 'immutable version';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_case_versions_immutable ON case_versions;
CREATE TRIGGER trg_case_versions_immutable
BEFORE UPDATE OR DELETE ON case_versions
FOR EACH ROW
WHEN (OLD.published_at IS NOT NULL)
EXECUTE FUNCTION block_published_case_versions();

CREATE OR REPLACE FUNCTION block_published_case_prizes() RETURNS trigger AS $$
BEGIN
    IF (SELECT published_at FROM case_versions WHERE id = OLD.version_id) IS NOT NULL THEN
        RAISE EXCEPTION 'immutable prizes';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_case_prizes_immutable ON case_prizes;
CREATE TRIGGER trg_case_prizes_immutable
BEFORE UPDATE OR DELETE ON case_prizes
FOR EACH ROW
EXECUTE FUNCTION block_published_case_prizes();