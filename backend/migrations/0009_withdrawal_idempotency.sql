-- 0009: withdrawals.idempotency_key — код (app/withdrawals/service.py) ожидает колонку,
-- которой не было ни в одной миграции (раньше добавлялась вручную).
ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS idempotency_key TEXT UNIQUE;
