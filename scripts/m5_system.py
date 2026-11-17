"""M5-ийн нэг дэлгүүрийн (CA_1) 100 барааг ажиллаж буй системд API-аар оруулж, нэг товшилтын урсгалаар
борлуулалт ба эрэлтийн таамаглал гаргуулна. M5-д нөөцийн файл байхгүй тул эрэлтийн таамаглал нь
нөөц тасалдлыг борлуулалтаас тооцоолох (stockout_est) аргыг ашиглана.
Хэрэглээ: python scripts/m5_system.py <upload/CA_1 хавтас> [--api http://localhost:8000/api/v1]"""
import argparse
import json
import time

import requests

ap = argparse.ArgumentParser()
ap.add_argument("folder")
ap.add_argument("--api", default="http://localhost:8000/api/v1")
ap.add_argument("--user", default="manager")
ap.add_argument("--password", default="manager-demo-pass")
a = ap.parse_args()
B = a.api
H = {"Authorization": "Bearer " + requests.post(B + "/auth/token", data={"username": a.user, "password": a.password}).json()["access_token"]}


def wait(job):
    while True:
        s = requests.get(B + f"/jobs/{job}", headers=H).json()
        if s["status"] not in ("queued", "running"):
            return s
        time.sleep(3)


tx = open(f"{a.folder}/transactions.csv", "rb").read()
ds = requests.post(B + "/datasets", headers=H, json={"name": "M5 Walmart CA_1", "source": "open_data"}).json()["id"]
prev = requests.post(B + f"/datasets/{ds}/preview", headers=H, files={"file": ("t.csv", tx, "text/csv")}).json()
mapping = {k: v for k, v in prev["suggested_mapping"].items() if v}
print("таньсан багана:", mapping)
t0 = time.time()
r = requests.post(B + f"/datasets/{ds}/versions", headers=H, files={"file": ("transactions.csv", tx, "text/csv")},
                  data={"mapping": json.dumps(mapping), "date_format": "%Y-%m-%d"}).json()
vid = r["version_id"]
print("импорт:", wait(r["job_id"])["status"], f"{time.time() - t0:.0f} с")
q = requests.get(B + f"/dataset-versions/{vid}/quality", headers=H).json()
print("чанар:", q["version"]["status"], "usable", q["usable"], {x["rule_id"]: x["n"] for x in q["by_rule"]} if "by_rule" in q else "")
d = requests.get(B + f"/experiments/defaults?dataset_version_id={vid}", headers=H).json()
print("өгөгдөл:", d["data"])
exps = {}
for target in ("sales", "demand"):
    p = d["protocol"]; p["sample"]["max_series"] = 100
    e = requests.post(B + "/experiments", headers=H, json={"name": f"M5 CA_1 — {target}", "dataset_version_id": vid,
                                                          "target": target, "protocol": p}).json()
    requests.post(B + f"/experiments/{e['id']}/validate?auto=true", headers=H)
    exps[target] = e["id"]
t0 = time.time()
for target, eid in exps.items():
    while True:
        e = requests.get(B + f"/experiments/{eid}", headers=H).json()
        if e["status"] == "test_done" or any(j["status"] == "failed" for j in e.get("jobs", [])):
            break
        time.sleep(10)
    print(target, eid, e["status"], f"{time.time() - t0:.0f} с")
print(json.dumps({"version": vid, "experiments": exps}))
