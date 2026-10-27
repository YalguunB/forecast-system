-- Сарын түвшний таамаглал (диплом §2.4, тэгшитгэл 2.1, 2.2; FR-04).
--   * Өдрийн цуваа (curated.daily_series, өдрийн төлөв) нь чанарын суурь хэвээр.
--   * Таамаглал: эхлэл o = мэдэгдэх сүүлийн сар (сарын эхний өдөр), h = 1..12 сар,
--     зорилтот сар = o + h сар. Хүрээ: 1 (сар), 3 (улирал), 12 (жил).
--   * Бүтээгдэхүүний ангилал (заавал биш) — ангиллаар тайлан гаргахад.
-- Өмнөх өдрийн туршилтын мөр шинэ CHECK-д тохирохгүй тул шалгалтыг NOT VALID-аар зөвхөн
-- шинэ мөрд хэрэглэж, хуучин туршилтуудыг архивлана (устгахгүй, аудит хэвээр).

ALTER TABLE curated.series ADD COLUMN IF NOT EXISTS product_category text;

ALTER TABLE forecast.forecast_value DROP CONSTRAINT IF EXISTS forecast_value_h_check;
ALTER TABLE forecast.forecast_value DROP CONSTRAINT IF EXISTS forecast_value_check;
ALTER TABLE forecast.forecast_value
  ADD CONSTRAINT forecast_value_h_month CHECK (h BETWEEN 1 AND 12) NOT VALID,
  ADD CONSTRAINT forecast_value_month_start CHECK (extract(day FROM origin_date) = 1) NOT VALID,
  ADD CONSTRAINT forecast_value_target_month
    CHECK (target_date = (origin_date + make_interval(months => h))::date) NOT VALID;

ALTER TABLE forecast.error_metric DROP CONSTRAINT IF EXISTS error_metric_horizon_check;
ALTER TABLE forecast.error_metric
  ADD CONSTRAINT error_metric_horizon_month CHECK (horizon IN (1, 3, 12)) NOT VALID;
ALTER TABLE forecast.error_metric DROP CONSTRAINT IF EXISTS error_metric_metric_check;
ALTER TABLE forecast.error_metric
  ADD CONSTRAINT error_metric_metric_check CHECK (metric IN
    ('MAE','RMSE','Bias','WAPE','MASE','RMSSE','SUM_AE','SUM_APE','PINBALL','COVERAGE','WIDTH'));

ALTER TABLE experiment.model_selection DROP CONSTRAINT IF EXISTS model_selection_horizon_check;
ALTER TABLE experiment.model_selection
  ADD CONSTRAINT model_selection_horizon_month CHECK (horizon IN (1, 3, 12)) NOT VALID;

ALTER TABLE curated.series_profile RENAME COLUMN train_n_days TO train_n_months;
ALTER TABLE curated.series_profile RENAME COLUMN acf7 TO acf12;

-- MonthlySeriesBuilder-ийн SQL хэлбэр (тайлан, экспортод): сарын нийлбэр ба бүрэн эсэх.
-- is_complete = сарын бүх өдөр цуваанд байгаа; has_records = сард дор хаяж нэг өдөр бүртгэлтэй.
CREATE OR REPLACE VIEW curated.monthly_series AS
SELECT dataset_version_id, series_id,
       date_trunc('month', day)::date                                   AS month,
       sum(sales_qty)                                                   AS sales_qty,
       sum(sales_amount)                                                AS sales_amount,
       count(*)                                                         AS n_days,
       count(*) FILTER (WHERE day_state IN ('missing', 'closed'))        AS n_gap,
       count(*) FILTER (WHERE day_state = 'stockout')                   AS n_stockout,
       count(*) = extract(day FROM date_trunc('month', min(day)) + interval '1 month - 1 day')::int
                                                                        AS is_complete,
       count(*) FILTER (WHERE day_state NOT IN ('missing', 'closed')) > 0 AS has_records
  FROM curated.daily_series
 GROUP BY 1, 2, 3;

GRANT SELECT ON curated.monthly_series TO fc_app;

-- Өдрийн түвшний хуучин туршилтуудыг архивлана (протоколд grain = month байхгүй).
UPDATE experiment.experiment SET archived_at = now()
 WHERE archived_at IS NULL AND NOT (protocol ? 'grain');
