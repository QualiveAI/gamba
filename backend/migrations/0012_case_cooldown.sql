-- 0012: кулдаун фрибет-кейсов (недельный/мега по отметкам)
ALTER TABLE cases ADD COLUMN IF NOT EXISTS cooldown_hours INT NOT NULL DEFAULT 0;
