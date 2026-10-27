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
