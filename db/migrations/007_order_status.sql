-- Захиалгын төлөв (Cancelled / Returned …) — онлайн дэлгүүрийн өгөгдөлд.
-- Цуцлагдсан захиалгыг борлуулалтад тооцохгүй, гэхдээ анхны мөр хэвээр хадгалагдана (Z2):
-- is_cancelled = true мөрийг өдрийн цуваа байгуулахдаа алгасна, DQ-11-ээр тайлагнана.
ALTER TABLE raw.raw_transaction ADD COLUMN IF NOT EXISTS order_status text;
ALTER TABLE raw.raw_transaction ADD COLUMN IF NOT EXISTS is_cancelled boolean NOT NULL DEFAULT false;

ALTER TABLE curated.data_quality_issue DROP CONSTRAINT IF EXISTS data_quality_issue_rule_id_check;
ALTER TABLE curated.data_quality_issue
  ADD CONSTRAINT data_quality_issue_rule_id_check CHECK (rule_id ~ '^DQ-(0[1-9]|1[01])$');

COMMENT ON COLUMN raw.raw_transaction.is_cancelled IS
  'Захиалгын төлөв цуцлагдсан (Cancelled, Void, Failed…) — борлуулалтад тооцохгүй (DQ-11)';
