# Борлуулалтын таамаглалын систем — v0.1 (босоо зүсэлт)

Дипломын ажлын 3–4-р бүлгийн зохиомжийн хэрэгжүүлэлт: React + Plotly ↔ FastAPI ↔ PostgreSQL ← Python worker.
Энэ хувилбар нь импортоос экспорт хүртэлх бүх урсгалыг төгсгөлөөс төгсгөл хүртэл ажиллуулна; загварын багц
суурь, ETS, Croston/SBA-аар хязгаарлагдана (SARIMA, Prophet, XGBoost нь 2-р үе шатанд).

## Эхлүүлэх

```bash
cp .env.example .env            # бүх нууц утгыг солино
docker compose up -d --build    # db → migrate → api, worker, web
open http://localhost:8080      # ADMIN_USERNAME / ADMIN_PASSWORD-оор нэвтэрнэ
make demo                       # синтетик өгөгдөл үүсгэж API-аар бүх урсгалыг ажиллуулна
```

`make demo` дараа нэвтрэх: `steward`, `analyst`, `manager`, `researcher` (нууц үг `<нэр>-demo-pass`).
Worker-ийг олшруулах: `docker compose up -d --scale worker=3`.

Docker-гүй хөгжүүлэлт: PostgreSQL 16 дээр `db/init/01_roles.sh`-ийн SQL-ийг ажиллуулж, дараа нь

```bash
cd backend && pip install -r requirements-dev.txt
OWNER_DATABASE_URL=postgresql://fc_owner:...@localhost/forecast python -m fcsys.migrate
DATABASE_URL=postgresql://fc_app:...@localhost/forecast ADMIN_PASSWORD=... uvicorn fcsys.api.main:app
DATABASE_URL=... python -m fcsys.engine.worker
cd ../frontend && npm install && npm run dev       # http://localhost:5173, /api → :8000
```

API баримт: `/api/v1/docs`.

## Бүтэц

| Хавтас | Агуулга | Зохиомж |
|---|---|---|
| `db/migrations/001_schema.sql` | 5 схем, 24 хүснэгт, түгжих ба зөвхөн-нэмэх trigger, CHECK | §4.3, Хүснэгт 4.4–4.6 |
| `db/migrations/002_seed_holidays.sql` | Монголын баяр 2021–2026 | FR-D7 |
| `db/migrations/003_grants.sql`, `db/init/01_roles.sh` | fc_owner (схем) / fc_app (API, worker) | §4.7 |
| `backend/fcsys/engine/` | ingest, validate, grid, profile, features, models, evaluate, select, protocol, report, jobs, worker | Хүснэгт 4.7 |
| `backend/fcsys/api/` | REST, JWT, эрхийн матриц, `{code,message,details}` алдаа | §4.5, Хүснэгт 4.9, 4.11 |
| `frontend/` | 7 дэлгэц, монгол хэлээр | §4.6, Хүснэгт 4.10 |
| `scripts/gen_synthetic.py` | seed-тэй синтетик өгөгдөл (бүх төлөв, DQ дүрмийг идэвхжүүлнэ) | — |
| `backend/tests/` | нэгж, алдагдал, DB дүрэм, API, дараалал, дахин ажиллуулах | §4.9 |

## Протоколын дүрмийг хаана хэрэгжүүлсэн (Хүснэгт 4.12)

| Дүрэм | Механизм | Шалгах тест |
|---|---|---|
| 1. Зорилтыг нэрлэх | `experiment.target` enum; API хариу, экспорт мөр бүрд `target_label` | `test_api_flow::test_full_flow` |
| 2. Гүйлгээгүй өдрийг 0 болгохгүй | `day_state` enum, `CHECK ((day_state='sold') = (sales_qty>0))` | `test_api_flow` (төлвүүд) |
| 3. Мэдээлэл ≤ o | `history.loc[:o]`, `known_at ≤ o`; загвар ирээдүйн өдөр хүлээж авбал `AssertionError` | `test_leakage` (Hypothesis) |
| 4. Нийтлэг эхлэл, цувааны багц | `origins_for` протоколоос; нэг дэд багц бүх run-д | `test_metrics::test_origin_counts_match_protocol` |
| 5. Сонголт validation-д | `CHECK (selected_on='validation')`; `select.py` тестийн алдаа уншдаггүй | `test_db_rules` |
| 6. Тестээс өмнө түгжих | статус зөвхөн нэг алхмаар урагш; protocol/selection hash нэг удаа; model_selection царцана | `test_db_rules` |
| 7. Тест нэг удаа | `test_job_id` нэг удаа; test run зөвхөн `locked` үед (trigger); давтан дуудахад 409 | `test_api_flow`, `test_db_rules` |
| 8. Бүтэлгүйтлийг нууцлахгүй | `run_failure` + fallback; тайланд бүтэлгүйтэл, хасагдсан цуваа шалтгаантай | `test_metrics::test_failure_falls_back...` |
| 9. Тодорхойгүй хэмжүүр | `CHECK (value IS NOT NULL OR undefined_reason IS NOT NULL)` | `test_metrics`, `test_db_rules` |
| 10. Залруулга анхныг дарахгүй | `original_value`-г сервер бичнэ; хүснэгт зөвхөн нэмнэ | `test_api_flow` |
| 11. Дахин ажиллуулах | run-д seed, `lib_versions`, `input_checksum`, `code_version`; цувааны seed = f(seed, series_id) | `test_reproducibility` |
| 12. Интервалгүй загварт зурвасгүй | `q_lo/q_hi NULL` → `interval.available=false` | `test_api_flow` |

Мөн: fc_app хэрэглэгч `ALTER TABLE ... DISABLE TRIGGER` хийж чадахгүй (`test_app_role_cannot_disable_triggers`).

## Функциональ шаардлагын хамрах хүрээ

M (28) — бүгд хэрэгжсэн, дараах хязгаартай: **FR-M1** нь 5 загвартай (naive, seasonal naive, ETS, Croston, SBA);
SARIMA, Prophet, XGBoost нэмэгдээгүй. **FR-M4** нь загвар, параметрийг сонгоно; ensemble-ийн жин хэрэгжээгүй.
**FR-S3** шинжийн модуль (хоцролт, гулсах статистик, календарь, үнэ) бичигдэж алдагдлын тест өнгөрсөн боловч
одоогийн загварууд түүнийг ашигладаггүй (XGBoost-д бэлэн).

S (8) — хэрэгжсэн: FR-D3, D7, E3, E4, F3 (төлөвтэй өдрийн тайлбар; шинжийн хувь нэмэр статистик загварт байхгүй), G2, A2.
Хэрэгжээгүй: **FR-M7** (шинжийн нэмэлт ашгийн туршилт — ML загвартай хамт).

C (4) — FR-D8 (нөөцийн импорт) хэрэгжсэн, D зорилт нөөцийн найдвартай өгөгдөлтэй үед зөвшөөрөгдөнө.
Хэрэгжээгүй: FR-M8, FR-E5, FR-G4.

## Зохиомжоос ялгаатай шийдвэр (баримтад тусгах)

1. **Ажлын төрөл нэмэгдсэн.** `validate`/`test` эцэг ажил цувааны багц бүрт `forecast_batch` хүүхэд ажил үүсгэж,
   сүүлийн хүүхэд `finalize`-ийг үүсгэнэ (§4.4 «багц бүр нэг job»-ийг шууд хэрэгжүүлсэн). `regrid` нь чанарын
   шийдвэрийг хэрэглэж өдрийн цувааг дахин байгуулна.
2. **Хүснэгтэд нэмсэн талбар:** `experiment.protocol_locked_at, test_job_id, archived_at`; `run.phase, role`;
   `job.parent_id, progress, cancel_requested`; `error_metric.origin_date` (NULL = эхлэлүүдийн дундаж).
   `forecast_value (run_id, split)` → `run (run_id, phase)` нийлмэл FK нь хуваалт, run-ийн шатыг таарахыг баталгаажуулна.
3. **DQ-02**: мөр бүр «анхааруулга» болж карантинд ордог; нийт мөрийн 1%-иас хэтэрвэл нэгтгэсэн «блоклох» асуудал үүснэ.
4. **DQ-06** (хэт утга) импортын үед бүх хувилбараас тооцогдоно; зохиомжид «сургалтын цонхноос» гэсэн. Мэдээллийн
   түвшинд л тэмдэглэдэг, утгыг өөрчилдөггүй тул загварт нөлөөгүй.
5. **Экспорт синхрон** (§4.5-д 202 гэсэн). Жижиг байгууллагын хэмжээнд хангалттай; том болбол ажил болгоно.
6. **Live таамаглал** (Зураг 3.2, 9-р алхам) тест ажлын хамт сонгогдсон загвараар автоматаар гарна.
7. **selection_level-ийн анхдагч = `global`** (нээлттэй асуудал байсан). Протоколд `series`/`group` сонгож болно.
8. **Endpoint нэмэгдсэн**: `preview`, `apply`, `series/{id}/days`, `experiments/defaults`, `forecasts/series`, `jobs` жагсаалт.
9. Тест/validation-ийн хуваалтыг өгөгдлийн сүүлийн өдрөөс тоолно: тест = сүүлийн 90, validation = түүний өмнөх 60 хоног.

## Юу шалгагдсан, юу шалгагдаагүй

Шалгасан (PostgreSQL 16.15, Python 3.13): `backend/tests` — 26 тест өнгөрсөн; синтетик өгөгдөл дээр HTTP API-аар
(`scripts/demo_seed.py`) хоёр worker-тэй бүх урсгал; frontend-ийг build хийж үндсэн дэлгэцийг хөтчөөр нүдээр шалгасан.

Шалгаагүй: Docker image-ийг энэ орчинд build хийгээгүй (`docker compose config` л хүчинтэй гэж гарсан); HTTPS
(урд талын reverse proxy-оор хангана); бодит байгууллагын өгөгдөл; хэрэглэгчийн пилот (NFR-5); NFR-4-ийн хэмжилт.
Синтетик өгөгдөл дээрх MASE зэрэг тоо нь системийн ажиллагааг харуулахаас өөр утгагүй — нарийвчлалын үр дүн биш.

Цагаан сарын огноо нь timeanddate.com-оос (2026-10-25 татсан, урьдчилсан байж болно); 2027 оноос хойш нэмнэ.

## Дараагийн үе шат (Хүснэгт 4.14)

2-р үе шат: SARIMA, Prophet, XGBoost (recursive, `features.py` ашиглана), ensemble-ийн жин, FR-M7.
3–4-р үе шат: FR-E5 (Diebold–Mariano), NFR-4 хэмжилт, пилот.
