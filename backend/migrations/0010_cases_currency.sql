-- 0010: валюта кейса: units (обычные) или freebets (фрибет-кейсы)
ALTER TABLE cases ADD COLUMN IF NOT EXISTS currency TEXT NOT NULL DEFAULT 'units';
