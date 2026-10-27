.PHONY: up down data demo test
data:    ## Синтетик өгөгдөл үүсгэх
	python3 scripts/gen_synthetic.py --out data/synthetic --seed 42
demo: data   ## API-аар демо урсгал ажиллуулах (ADMIN_PASSWORD .env-ээс)
	python3 scripts/demo_seed.py --api http://localhost:$${WEB_PORT:-8080}/api/v1 --admin-password $$(grep ^ADMIN_PASSWORD .env | cut -d= -f2) --data data/synthetic
test:    ## Тест (PostgreSQL 16 superuser шаардлагатай: TEST_PG_SUPER_URL)
	cd backend && python3 -m pytest -q
