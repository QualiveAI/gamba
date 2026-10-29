ALTER TABLE withdrawals DROP CONSTRAINT IF EXISTS withdrawals_status_check;
ALTER TABLE withdrawals ADD CONSTRAINT withdrawals_status_check
  CHECK (status IN ('pending','frozen','approved','rejected','issued','manual_review','pending_supplier'));