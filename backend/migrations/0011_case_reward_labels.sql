-- 0011: предметы в наградах кейсов — видимое название с ценой
ALTER TABLE case_rewards ADD COLUMN IF NOT EXISTS label TEXT;
