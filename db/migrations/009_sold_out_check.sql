-- 008-аар нэмсэн 'sold_out' утгыг тусдаа гүйлгээнд ашиглана (PostgreSQL: шинэ enum утгыг нэмсэн гүйлгээндээ ашиглаж болохгүй).
-- Борлуулалттай өдөр = 'sold' эсвэл 'sold_out'.
ALTER TABLE curated.daily_series DROP CONSTRAINT IF EXISTS daily_series_check1;
ALTER TABLE curated.daily_series DROP CONSTRAINT IF EXISTS daily_series_check;
ALTER TABLE curated.daily_series
  ADD CONSTRAINT daily_series_check CHECK (sales_qty >= 0 AND returns_qty >= 0);
ALTER TABLE curated.daily_series
  ADD CONSTRAINT daily_series_sold_state_check CHECK ((day_state IN ('sold', 'sold_out')) = (sales_qty > 0));
