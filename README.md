# Борлуулалтын таамаглалын систем — v0.1
## Эхлүүлэх``


Frontend-ийг дангаар нь хөгжүүлэхдээ `frontend` хавтас руу орж `npm install`, дараа нь
`npm run dev` ажиллуулна. Энэ скрипт үндсэн хавтсанд биш `frontend/package.json`-д бий.
Vite `http://localhost:5173` дээр ажиллаж, `/api` хүсэлтийг `http://localhost:8000` руу дамжуулна.

PostgreSQL 16 дээр `db/init/01_roles.sh`-ийн SQL-ийг ажиллуулж, дараа нь

```bash
cd backend && pip install -r requirements-dev.txt
OWNER_DATABASE_URL=postgresql://fc_owner:...@localhost/forecast python -m fcsys.migrate
DATABASE_URL=postgresql://fc_app:...@localhost/forecast ADMIN_PASSWORD=... uvicorn fcsys.api.main:app
DATABASE_URL=... python -m fcsys.engine.worker
cd ../frontend && npm install && npm run dev       # http://localhost:5173, /api → :8000
```

## v0.2 — менежерт ойлгомжтой, эрэлтэд чиглэсэн сайжруулалт

- **Нэг товшилтын таамаглал.** «Таамаглал гаргуулах» дарахад аргуудыг турших → сонгох → түгжих → эцсийн шалгалт →
  ирэх 12 сарын таамаглал дараалан автоматаар явагдана (`POST /experiments/{id}/validate?auto=true`).
  Дүрэм хэвээр: арга зөвхөн validation-аас сонгогдоно, эцсийн шалгалт нэг л удаа. «Алхам бүрийг өөрөө батлах» сонголт хэвээр.
- **Гүйцэтгэл** (шинэ хуудас, `GET /forecasts/tracking`). Таамагласан саруудын бодит борлуулалтыг ижил багцад шинэ файлаар
  оруулмагц таамаглал ба бодит утгыг сар, бараагаар харьцуулна. Бодит утга бүрдээгүй сарыг тооцохгүй (алдааг 0 гэж харуулахгүй).
  Гараар зассан утгын нөлөөг системийн анхны таамаглалтай харьцуулж харуулна.
- **Хосолсон арга** (`combo`): ETS, ETS + тренд, SARIMA-ийн тэнцүү жинтэй дундаж. Анхдагч протоколд нэмэгдсэн.
- **Нүүр хуудасны гол дүн.** Ирэх 12 сарын нийт таамаглал, найдвартай байдал, бодит гүйцэтгэл нэг дор.

Эрэлтийн шалгалт (жинхэнэ эрэлт нь мэдэгдэх синтетик өгөгдөл): `scripts/gen_demand_test.py`, `scripts/check_demand_test.py`.
