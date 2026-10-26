-- =====================================================================
-- Борлуулалтын таамаглалын систем — өгөгдлийн сангийн схем (v1)
-- Зохиомж: 4-р бүлэг §4.3, Хүснэгт 4.4–4.6; протоколын механизм §4.8.
-- 5 схем, 24 хүснэгт. Энэ файлыг МИГРАЦИЙН хэрэглэгч (fc_owner) ажиллуулна;
-- API ба worker нь fc_app хэрэглэгчээр холбогдох тул trigger-ийг унтрааж,
-- схемийг өөрчилж чадахгүй (§4.7, NFR-3).
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS curated;
CREATE SCHEMA IF NOT EXISTS experiment;
CREATE SCHEMA IF NOT EXISTS forecast;
CREATE SCHEMA IF NOT EXISTS governance;

-- ---------------------------------------------------------------------
-- Нийтлэг төрөл
-- ---------------------------------------------------------------------
CREATE TYPE curated.day_state AS ENUM
  ('sold','open_no_sale','stockout','closed','missing','unknown');      -- §3.8, Хүснэгт 3.8
CREATE TYPE experiment.target_kind AS ENUM ('sales','demand');           -- Z1
CREATE TYPE curated.price_kind AS ENUM ('actual','approved_plan','scenario');  -- FR-D7
CREATE TYPE curated.dq_severity AS ENUM ('blocking','warning','info');   -- Хүснэгт 3.9

-- Мөр өөрчлөх, устгахыг бүрэн хориглох ерөнхий trigger функц (зөвхөн нэмнэ)
CREATE FUNCTION governance.forbid_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '%.%: % is not allowed (append-only table)',
    TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'integrity_constraint_violation';
END $$ LANGUAGE plpgsql;

-- =====================================================================
-- governance (1/2): хэрэглэгч — бусад хүснэгт created_by-аар заадаг
-- =====================================================================
CREATE TABLE governance.app_user (
  id             bigserial PRIMARY KEY,
  username       text NOT NULL UNIQUE,
  full_name      text NOT NULL DEFAULT '',
  password_hash  text NOT NULL,
  roles          text[] NOT NULL DEFAULT '{}',
  is_active      boolean NOT NULL DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now(),
  CHECK (roles <@ ARRAY['data_steward','analyst','manager','researcher','admin']::text[])
);

-- =====================================================================
-- raw: анхны өгөгдөл, өөрчлөгдөхгүй (Z2, FR-D2, NFR-3)
-- =====================================================================
CREATE TABLE raw.dataset (
  id          bigserial PRIMARY KEY,
  name        text NOT NULL UNIQUE,
  description text NOT NULL DEFAULT '',
  source      text NOT NULL DEFAULT 'organization'
              CHECK (source IN ('organization','open_data','synthetic')),
  created_by  bigint NOT NULL REFERENCES governance.app_user(id),
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE raw.dataset_version (
  id            bigserial PRIMARY KEY,
  dataset_id    bigint NOT NULL REFERENCES raw.dataset(id),
  version_no    int    NOT NULL,
  file_name     text   NOT NULL,
  stored_path   text   NOT NULL,
  sha256        text   NOT NULL,
  mapping       jsonb  NOT NULL,           -- талбарын зураглал, огнооны хэлбэр, нэгж (FR-D3)
  subset_rule   jsonb,                     -- нээлттэй өгөгдлийн дэд багц, seed (FR-D9)
  imported_at   timestamptz NOT NULL DEFAULT now(),
  imported_by   bigint NOT NULL REFERENCES governance.app_user(id),
  row_count     int,
  date_min      date,
  date_max      date,
  status        text NOT NULL DEFAULT 'imported'
                CHECK (status IN ('imported','validated','failed')),
  archived_at   timestamptz,               -- FR-A2: устгахгүй, архивлана
  UNIQUE (dataset_id, version_no),
  CHECK (date_min IS NULL OR date_max IS NULL OR date_min <= date_max)
);
CREATE INDEX ON raw.dataset_version (dataset_id, sha256);

CREATE TABLE raw.raw_transaction (
  id                 bigserial PRIMARY KEY,
  dataset_version_id bigint NOT NULL REFERENCES raw.dataset_version(id),
  source_row         int    NOT NULL,      -- файлын мөрийн дугаар (асуудлыг заахад)
  txn_id             text,
  txn_date           date,                 -- NULL = уншигдаагүй (DQ-02 карантин)
  txn_date_raw       text   NOT NULL,
  product_ext_id     text   NOT NULL,
  branch_ext_id      text   NOT NULL,
  qty                double precision,     -- NULL = тоо биш (DQ-01)
  unit               text   NOT NULL,
  amount             double precision,
  is_return          boolean NOT NULL DEFAULT false
);
CREATE INDEX ON raw.raw_transaction (dataset_version_id, product_ext_id, branch_ext_id, txn_date);
CREATE TRIGGER raw_transaction_immutable BEFORE UPDATE OR DELETE ON raw.raw_transaction
  FOR EACH ROW EXECUTE FUNCTION governance.forbid_mutation();

-- =====================================================================
-- curated: цуваа, өдрийн төлөв, шинжийн эх, чанарын асуудал
-- =====================================================================
CREATE TABLE curated.series (
  id          bigserial PRIMARY KEY,
  dataset_id  bigint NOT NULL REFERENCES raw.dataset(id),
  product_id  text   NOT NULL,
  branch_id   text   NOT NULL,
  unit        text   NOT NULL,
  UNIQUE (dataset_id, product_id, branch_id)
);

CREATE TABLE curated.daily_series (
  dataset_version_id bigint NOT NULL REFERENCES raw.dataset_version(id),
  series_id          bigint NOT NULL REFERENCES curated.series(id),
  day                date   NOT NULL,
  sales_qty          double precision NOT NULL DEFAULT 0,   -- цэвэр борлуулалт (буцаалтыг хассан, ≥ 0)
  returns_qty        double precision NOT NULL DEFAULT 0,   -- DQ-05: тусад нь
  sales_amount       double precision,                      -- орлого, зорилтоос тусад (FR-S1)
  day_state          curated.day_state NOT NULL,            -- гүйлгээгүй өдөр ч төлөвтэй (FR-D5)
  PRIMARY KEY (dataset_version_id, series_id, day),
  CHECK (sales_qty >= 0 AND returns_qty >= 0),
  CHECK ((day_state = 'sold') = (sales_qty > 0))
);
CREATE INDEX ON curated.daily_series (series_id, day);

CREATE TABLE curated.price_record (
  id                 bigserial PRIMARY KEY,
  dataset_version_id bigint NOT NULL REFERENCES raw.dataset_version(id),
  series_id          bigint NOT NULL REFERENCES curated.series(id),
  valid_from         date   NOT NULL,
  price              double precision NOT NULL CHECK (price >= 0),
  price_kind         curated.price_kind NOT NULL,
  known_at           date   NOT NULL                       -- FR-S4: хэзээ мэдэгдсэн
);
CREATE INDEX ON curated.price_record (dataset_version_id, series_id, valid_from);

CREATE TABLE curated.promotion (
  id                 bigserial PRIMARY KEY,
  dataset_version_id bigint NOT NULL REFERENCES raw.dataset_version(id),
  series_id          bigint REFERENCES curated.series(id),  -- NULL = бүх бүтээгдэхүүн
  day_from           date NOT NULL,
  day_to             date NOT NULL,
  promo_kind         text NOT NULL DEFAULT 'promo',
  known_at           date NOT NULL,
  CHECK (day_from <= day_to)
);

CREATE TABLE curated.calendar_day (
  dataset_version_id bigint NOT NULL REFERENCES raw.dataset_version(id),
  branch_id          text   NOT NULL,
  day                date   NOT NULL,
  is_open            boolean NOT NULL,
  PRIMARY KEY (dataset_version_id, branch_id, day)
);

CREATE TABLE curated.holiday (               -- Монголын баярын календарь (FR-D7)
  day      date NOT NULL,
  name     text NOT NULL,
  country  text NOT NULL DEFAULT 'MN',
  PRIMARY KEY (country, day, name)
);

CREATE TABLE curated.inventory_snapshot (    -- өргөтгөл (FR-D8, UC-08)
  dataset_version_id bigint NOT NULL REFERENCES raw.dataset_version(id),
  series_id          bigint NOT NULL REFERENCES curated.series(id),
  day                date   NOT NULL,
  on_hand            double precision,
  available          boolean NOT NULL,
  reliability        text NOT NULL DEFAULT 'unverified'
                     CHECK (reliability IN ('reliable','unverified','unreliable')),
  PRIMARY KEY (dataset_version_id, series_id, day)
);

CREATE TABLE curated.data_quality_issue (
  id                 bigserial PRIMARY KEY,
  dataset_version_id bigint NOT NULL REFERENCES raw.dataset_version(id),
  rule_id            text NOT NULL CHECK (rule_id ~ '^DQ-(0[1-9]|10)$'),
  severity           curated.dq_severity NOT NULL,
  series_id          bigint REFERENCES curated.series(id),
  day                date,
  source_row         int,
  message            text NOT NULL,
  original_value     text,                 -- FR-D6: анхны утга хадгалагдана
  corrected_value    text,
  action             text NOT NULL DEFAULT 'open'
                     CHECK (action IN ('open','accepted','corrected','excluded')),
  reason             text,
  resolved_by        bigint REFERENCES governance.app_user(id),
  resolved_at        timestamptz,
  CHECK (action = 'open' OR (reason IS NOT NULL AND resolved_by IS NOT NULL)),
  CHECK (action <> 'corrected' OR corrected_value IS NOT NULL)
);
CREATE INDEX ON curated.data_quality_issue (dataset_version_id, severity);

CREATE FUNCTION curated.keep_original_value() RETURNS trigger AS $$
BEGIN
  IF NEW.original_value IS DISTINCT FROM OLD.original_value
     OR NEW.rule_id IS DISTINCT FROM OLD.rule_id
     OR NEW.dataset_version_id IS DISTINCT FROM OLD.dataset_version_id THEN
    RAISE EXCEPTION 'data_quality_issue %: original_value/rule are immutable', OLD.id;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER dq_issue_keep_original BEFORE UPDATE ON curated.data_quality_issue
  FOR EACH ROW EXECUTE FUNCTION curated.keep_original_value();
CREATE TRIGGER dq_issue_no_delete BEFORE DELETE ON curated.data_quality_issue
  FOR EACH ROW EXECUTE FUNCTION governance.forbid_mutation();

-- =====================================================================
-- experiment: туршилт, түгжилт, run, сонголт (Z4)
-- =====================================================================
CREATE TABLE experiment.experiment (
  id                  bigserial PRIMARY KEY,
  name                text   NOT NULL,
  dataset_version_id  bigint NOT NULL REFERENCES raw.dataset_version(id),
  target              experiment.target_kind NOT NULL,
  protocol            jsonb  NOT NULL,
  protocol_hash       text,
  selection_hash      text,
  status              text   NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','validating','validation_done','locked','test_done')),
  protocol_locked_at  timestamptz,
  locked_at           timestamptz,         -- сонголт түгжигдсэн мөч
  test_job_id         bigint,              -- тест нэг удаа (§4.8 дүрэм 7)
  created_by          bigint NOT NULL REFERENCES governance.app_user(id),
  created_at          timestamptz NOT NULL DEFAULT now(),
  archived_at         timestamptz,
  CHECK (status = 'draft' OR protocol_hash IS NOT NULL),
  CHECK (status NOT IN ('locked','test_done') OR selection_hash IS NOT NULL)
);

-- §4.3-ын trigger (PostgreSQL 16.15 дээр шалгасан хувилбар) + нэг алхмаар урагшлах дүрэм
CREATE FUNCTION experiment.forbid_locked_change() RETURNS trigger AS $$
DECLARE
  order_ text[] := ARRAY['draft','validating','validation_done','locked','test_done'];
  old_pos int := array_position(order_, OLD.status);
  new_pos int := array_position(order_, NEW.status);
BEGIN
  IF new_pos < old_pos THEN
    RAISE EXCEPTION 'experiment %: status cannot move backwards (% -> %)',
      OLD.id, OLD.status, NEW.status;
  END IF;
  IF new_pos > old_pos + 1 THEN
    RAISE EXCEPTION 'experiment %: status cannot skip steps (% -> %)',
      OLD.id, OLD.status, NEW.status;
  END IF;
  IF OLD.status <> 'draft'
     AND (NEW.protocol IS DISTINCT FROM OLD.protocol
          OR NEW.target IS DISTINCT FROM OLD.target
          OR NEW.dataset_version_id IS DISTINCT FROM OLD.dataset_version_id) THEN
    RAISE EXCEPTION 'experiment % is locked', OLD.id;
  END IF;
  IF (OLD.protocol_hash IS NOT NULL
      AND NEW.protocol_hash IS DISTINCT FROM OLD.protocol_hash)
  OR (OLD.selection_hash IS NOT NULL
      AND NEW.selection_hash IS DISTINCT FROM OLD.selection_hash)
  OR (OLD.test_job_id IS NOT NULL
      AND NEW.test_job_id IS DISTINCT FROM OLD.test_job_id) THEN
    RAISE EXCEPTION 'experiment %: hash / test job is immutable once set', OLD.id;
  END IF;
  IF NEW.test_job_id IS NOT NULL AND OLD.test_job_id IS NULL AND OLD.status <> 'locked' THEN
    RAISE EXCEPTION 'experiment %: test can only start when locked', OLD.id;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER experiment_lock BEFORE UPDATE ON experiment.experiment
  FOR EACH ROW EXECUTE FUNCTION experiment.forbid_locked_change();
CREATE TRIGGER experiment_no_delete BEFORE DELETE ON experiment.experiment
  FOR EACH ROW EXECUTE FUNCTION governance.forbid_mutation();

CREATE TABLE experiment.series_sample (       -- FR-D9: дүрэм ба seed заавал
  id             bigserial PRIMARY KEY,
  experiment_id  bigint NOT NULL UNIQUE REFERENCES experiment.experiment(id),
  rule           jsonb  NOT NULL,
  seed           int    NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE experiment.series_sample_item (
  sample_id   bigint NOT NULL REFERENCES experiment.series_sample(id),
  series_id   bigint NOT NULL REFERENCES curated.series(id),
  included    boolean NOT NULL,             -- false = хасагдсан (тайланд шалтгаантай)
  exclude_reason text,
  PRIMARY KEY (sample_id, series_id),
  CHECK (included OR exclude_reason IS NOT NULL)
);

CREATE TABLE curated.series_profile (         -- FR-S2: зөвхөн сургалтын цонхноос
  experiment_id  bigint NOT NULL REFERENCES experiment.experiment(id),
  series_id      bigint NOT NULL REFERENCES curated.series(id),
  train_n_days   int    NOT NULL,
  n_pos          int    NOT NULL,
  adi            double precision,
  cv2            double precision,
  zero_share     double precision NOT NULL,
  acf7           double precision,
  seasonal_strength double precision,
  class          text   NOT NULL CHECK (class IN ('smooth','erratic','intermittent','lumpy','no_demand')),
  PRIMARY KEY (experiment_id, series_id)
);

CREATE TABLE experiment.run (                 -- FR-M9, Z8
  run_id          bigserial PRIMARY KEY,
  experiment_id   bigint NOT NULL REFERENCES experiment.experiment(id),
  phase           text   NOT NULL CHECK (phase IN ('validation','test','live')),
  role            text   NOT NULL DEFAULT 'candidate'
                  CHECK (role IN ('candidate','selected','baseline')),
  model           text   NOT NULL,
  feature_set     text   NOT NULL,
  params          jsonb  NOT NULL,
  seed            int    NOT NULL,
  code_version    text   NOT NULL,
  lib_versions    jsonb  NOT NULL,
  input_checksum  text   NOT NULL,
  started_at      timestamptz NOT NULL DEFAULT now(),
  finished_at     timestamptz,
  runtime_ms      bigint,
  status          text   NOT NULL DEFAULT 'running'
                  CHECK (status IN ('running','done','failed','cancelled')),
  UNIQUE (run_id, phase),                    -- forecast_value (run_id, split) FK-д
  UNIQUE (experiment_id, phase, model, params)
);

-- Run үүсгэх нь туршилтын төлөвт захирагдана: validation зөвхөн validating үед,
-- test/live зөвхөн locked үед (тест нэг удаа, §4.8 дүрэм 6–7).
CREATE FUNCTION experiment.run_phase_guard() RETURNS trigger AS $$
DECLARE st text;
BEGIN
  SELECT status INTO st FROM experiment.experiment WHERE id = NEW.experiment_id;
  IF NEW.phase = 'validation' AND st <> 'validating' THEN
    RAISE EXCEPTION 'validation run requires experiment status validating (is %)', st;
  ELSIF NEW.phase IN ('test','live') AND st <> 'locked' THEN
    RAISE EXCEPTION '% run requires experiment status locked (is %)', NEW.phase, st;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER run_phase_guard BEFORE INSERT ON experiment.run
  FOR EACH ROW EXECUTE FUNCTION experiment.run_phase_guard();

CREATE TABLE experiment.model_selection (     -- FR-M4
  experiment_id    bigint NOT NULL REFERENCES experiment.experiment(id),
  series_id        bigint NOT NULL REFERENCES curated.series(id),
  horizon          smallint NOT NULL CHECK (horizon IN (7,14,30)),
  run_id           bigint NOT NULL REFERENCES experiment.run(run_id),
  rule             text   NOT NULL,
  selection_level  text   NOT NULL CHECK (selection_level IN ('series','group','global')),
  score            double precision,
  selected_on      text   NOT NULL CHECK (selected_on = 'validation'),
  PRIMARY KEY (experiment_id, series_id, horizon)
);

CREATE FUNCTION experiment.selection_guard() RETURNS trigger AS $$
DECLARE st text; eid bigint;
BEGIN
  eid := COALESCE(NEW.experiment_id, OLD.experiment_id);
  SELECT status INTO st FROM experiment.experiment WHERE id = eid;
  IF st <> 'validating' THEN
    RAISE EXCEPTION 'model_selection of experiment % is frozen (status %)', eid, st;
  END IF;
  RETURN COALESCE(NEW, OLD);
END $$ LANGUAGE plpgsql;
CREATE TRIGGER model_selection_guard BEFORE INSERT OR UPDATE OR DELETE ON experiment.model_selection
  FOR EACH ROW EXECUTE FUNCTION experiment.selection_guard();

-- =====================================================================
-- forecast: таамаглал, алдаа, бүтэлгүйтэл
-- =====================================================================
CREATE TABLE forecast.forecast_value (
  run_id      bigint NOT NULL,
  series_id   bigint NOT NULL REFERENCES curated.series(id),
  split       text   NOT NULL CHECK (split IN ('validation','test','live')),
  origin_date date   NOT NULL,
  h           smallint NOT NULL CHECK (h BETWEEN 1 AND 30),
  target_date date   NOT NULL,
  y_hat       double precision NOT NULL,
  q_lo        double precision,              -- NULL = интервалгүй загвар (FR-E4)
  q_hi        double precision,
  PRIMARY KEY (run_id, series_id, split, origin_date, h),
  FOREIGN KEY (run_id, split) REFERENCES experiment.run (run_id, phase),
  CHECK (target_date = origin_date + h),
  CHECK ((q_lo IS NULL) = (q_hi IS NULL)),
  CHECK (q_lo IS NULL OR q_lo <= q_hi)
);
CREATE INDEX ON forecast.forecast_value (series_id, split, origin_date);

CREATE TABLE forecast.error_metric (
  id               bigserial PRIMARY KEY,
  run_id           bigint NOT NULL,
  series_id        bigint NOT NULL REFERENCES curated.series(id),
  split            text   NOT NULL CHECK (split IN ('validation','test')),
  origin_date      date,                     -- NULL = эхлэлүүдийн дундаж
  horizon          smallint NOT NULL CHECK (horizon IN (7,14,30)),
  metric           text   NOT NULL CHECK (metric IN
                     ('MAE','RMSE','Bias','WAPE','MASE','RMSSE','SUM_AE',
                      'PINBALL','COVERAGE','WIDTH')),
  value            double precision,
  n_pairs          int    NOT NULL,
  undefined_reason text,
  FOREIGN KEY (run_id, split) REFERENCES experiment.run (run_id, phase),
  CHECK (value IS NOT NULL OR undefined_reason IS NOT NULL)          -- §4.8 дүрэм 9
);
CREATE UNIQUE INDEX error_metric_key ON forecast.error_metric
  (run_id, series_id, split, horizon, metric, COALESCE(origin_date, '-infinity'::date));

CREATE TABLE forecast.run_failure (           -- FR-M6, Z5
  id              bigserial PRIMARY KEY,
  run_id          bigint NOT NULL REFERENCES experiment.run(run_id),
  series_id       bigint NOT NULL REFERENCES curated.series(id),
  origin_date     date   NOT NULL,
  reason          text   NOT NULL,
  fallback_model  text   NOT NULL,
  UNIQUE (run_id, series_id, origin_date)
);

-- =====================================================================
-- governance (2/2): залруулга, аудит, ажлын дараалал
-- =====================================================================
CREATE TABLE governance.forecast_adjustment (  -- FR-G1: анхных дарагдахгүй
  id              bigserial PRIMARY KEY,
  run_id          bigint NOT NULL REFERENCES experiment.run(run_id),
  series_id       bigint NOT NULL REFERENCES curated.series(id),
  target_date     date   NOT NULL,
  original_value  double precision NOT NULL,
  adjusted_value  double precision NOT NULL CHECK (adjusted_value >= 0),
  reason          text   NOT NULL CHECK (length(trim(reason)) > 0),
  user_id         bigint NOT NULL REFERENCES governance.app_user(id),
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON governance.forecast_adjustment (run_id, series_id, target_date, created_at DESC);
CREATE TRIGGER adjustment_append_only BEFORE UPDATE OR DELETE ON governance.forecast_adjustment
  FOR EACH ROW EXECUTE FUNCTION governance.forbid_mutation();

CREATE TABLE governance.audit_log (            -- FR-G3: зөвхөн нэмнэ
  id           bigserial PRIMARY KEY,
  user_id      bigint REFERENCES governance.app_user(id),
  action       text NOT NULL,
  object_type  text NOT NULL,
  object_id    text,
  at           timestamptz NOT NULL DEFAULT now(),
  detail       jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX ON governance.audit_log (at DESC);
CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON governance.audit_log
  FOR EACH ROW EXECUTE FUNCTION governance.forbid_mutation();

CREATE TABLE governance.job (                  -- A1: PostgreSQL дээрх ажлын дараалал
  id               bigserial PRIMARY KEY,
  parent_id        bigint REFERENCES governance.job(id),
  type             text  NOT NULL CHECK (type IN
                     ('import','regrid','validate','forecast_batch','finalize','test')),
  payload          jsonb NOT NULL DEFAULT '{}',
  status           text  NOT NULL DEFAULT 'queued'
                   CHECK (status IN ('queued','running','done','failed','cancelled')),
  attempts         int   NOT NULL DEFAULT 0,
  locked_by        text,
  progress         jsonb NOT NULL DEFAULT '{}',
  cancel_requested boolean NOT NULL DEFAULT false,
  created_by       bigint REFERENCES governance.app_user(id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  started_at       timestamptz,
  finished_at      timestamptz,
  error            text
);
CREATE INDEX job_queued ON governance.job (id) WHERE status = 'queued';
CREATE INDEX ON governance.job (parent_id);

ALTER TABLE experiment.experiment
  ADD CONSTRAINT experiment_test_job_fk FOREIGN KEY (test_job_id) REFERENCES governance.job(id);
