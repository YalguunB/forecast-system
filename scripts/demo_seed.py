"""Демо өгөгдөл ачаалагч — HTTP API-аар бүх урсгалыг ажиллуулна (worker ажиллаж байх ёстой).

  python scripts/demo_seed.py --api http://localhost:8080/api/v1 --admin-password <ADMIN_PASSWORD> --data data/synthetic

Үүсгэх хэрэглэгч (нууц үг = <нэр>-demo-pass): manager (менежер), executive (удирдлага).
Синтетик өгөгдлийг импортолж, блоклох асуудлыг хасаад, туршилтыг validation → түгжих → тест хүртэл ажиллуулна.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

MAPPING = {"txn_date": "sale_date", "product_id": "item", "branch_id": "store", "qty": "quantity", "unit": "uom",
           "txn_id": "receipt_no", "amount": "revenue", "is_return": "is_return"}
USERS = {"manager": ["manager"], "executive": ["executive"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8080/api/v1")
    ap.add_argument("--admin", default="admin")
    ap.add_argument("--admin-password", required=True)
    ap.add_argument("--data", default="data/synthetic")
    ap.add_argument("--max-series", type=int, default=30)
    a = ap.parse_args()
    c = httpx.Client(base_url=a.api, timeout=120)
    data = Path(a.data)

    def login(u, p):
        r = c.post("/auth/token", data={"username": u, "password": p})
        r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    def wait(job_id, h):
        while True:
            j = c.get(f"/jobs/{job_id}", headers=h).json()
            print(f"  ажил #{job_id}: {j['status']} {j.get('percent') or ''}", end="\r")
            if j["status"] in ("done", "failed", "cancelled"):
                print()
                if j["status"] != "done":
                    sys.exit(f"Ажил бүтэлгүйтэв: {j.get('error')}")
                return j
            time.sleep(2)

    admin = login(a.admin, a.admin_password)
    tok = {}
    for name, roles in USERS.items():
        c.post("/users", headers=admin, json={"username": name, "password": f"{name}-demo-pass", "roles": roles,
                                              "branches": ["*"], "full_name": name.capitalize()})
        tok[name] = login(name, f"{name}-demo-pass")
    st = rs = tok["manager"]

    print("1. Импорт")
    ds = c.post("/datasets", headers=st, json={"name": f"Синтетик дэлгүүр {int(time.time())}", "source": "synthetic"}).json()
    files = {"file": ("transactions.csv", (data / "transactions.csv").read_bytes(), "text/csv")}
    for k, f in (("price_file", "prices.csv"), ("calendar_file", "calendar.csv"), ("inventory_file", "inventory.csv")):
        files[k] = (f, (data / f).read_bytes(), "text/csv")
    r = c.post(f"/datasets/{ds['id']}/versions", headers=st, files=files, data={
        "mapping": json.dumps(MAPPING), "date_format": "%Y-%m-%d",
        "unit_conversions": json.dumps([{"product_id": "P005", "from": "хайрцаг", "to": "ширхэг", "factor": 12}])})
    r.raise_for_status()
    vid = r.json()["version_id"]
    wait(r.json()["job_id"], st)

    print("2. Блоклох асуудлыг шийдэх")
    for it in c.get(f"/dataset-versions/{vid}/issues?severity=blocking", headers=st).json()["items"]:
        c.patch(f"/issues/{it['id']}", headers=st, json={"action": "excluded" if it["source_row"] else "accepted",
                                                        "reason": "Демо: тоо биш хэмжээтэй мөрийг хасав"})
    wait(c.post(f"/dataset-versions/{vid}/apply", headers=st).json()["job_id"], st)

    print("3. Туршилт: validation → түгжих → тест")
    proto = c.get(f"/experiments/defaults?dataset_version_id={vid}", headers=rs).json()["protocol"]   # сарын тоонд тохирсон
    proto["sample"]["max_series"] = a.max_series
    e = c.post("/experiments", headers=rs, json={"name": "Сарын таамаглал (S)", "dataset_version_id": vid, "target": "sales",
                                                 "protocol": proto}).json()
    wait(c.post(f"/experiments/{e['id']}/validate", headers=rs).json()["job_id"], rs)
    c.post(f"/experiments/{e['id']}/lock", headers=rs).raise_for_status()
    wait(c.post(f"/experiments/{e['id']}/test", headers=rs).json()["job_id"], rs)
    print(f"Бэлэн: туршилт #{e['id']}. Нэвтрэх: manager / manager-demo-pass, executive / executive-demo-pass")


if __name__ == "__main__":
    main()
