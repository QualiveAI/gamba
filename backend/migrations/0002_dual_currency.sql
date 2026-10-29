-- 0002_dual_currency.sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS balance_freebets BIGINT NOT NULL DEFAULT 0 CHECK (balance_freebets >= 0);
-- rename balance_units? keep
ALTER TABLE ledger_entries ADD COLUMN IF NOT EXISTS currency TEXT NOT NULL DEFAULT 'units' CHECK (currency IN ('units','freebets'));

-- unique index
CREATE UNIQUE INDEX IF NOT EXISTS idx_ledger_user_currency_ref ON ledger_entries(user_id, currency, ref_id) WHERE ref_id IS NOT NULL;

-- ensure existing rows currency units
UPDATE ledger_entries SET currency = 'units' WHERE currency IS NULL;