-- 0014: крутки за отметки: 7 дней -> недельный кейс, 30 дней -> мега
ALTER TABLE users ADD COLUMN IF NOT EXISTS weekly_spins INT NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS mega_spins INT NOT NULL DEFAULT 0;
