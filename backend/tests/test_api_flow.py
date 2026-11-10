"""Төгсгөлөөс төгсгөл (§4.9 «Интеграци», «API»): импорт → чанар → туршилт → түгжих → тест →
таамаглал → залруулга → экспорт. Эрхийн матриц (Хүснэгт 4.11), 409/422, асинхрон ажил."""
import io
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from fcsys.api.core import hash_password
from fcsys.engine.worker import drain

MAPPING = {"txn_date": "sale_date", "product_id": "item", "branch_id": "store", "qty": "quantity",
           "unit": "uom", "txn_id": "receipt_no", "amount": "revenue", "is_return": "is_return"}


@pytest.fixture(scope="module")
def client(database):
    from fcsys.api.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def users(client, database):
    from fcsys.db import connect
    with connect(database["app"]) as conn:
        conn.execute("INSERT INTO governance.app_user (username, password_hash, roles) VALUES ('root', %s, '{admin}') "
                     "ON CONFLICT (username) DO NOTHING", (hash_password("root-pass-123"),))
        conn.commit()
    tok = {"admin": _login(client, "root", "root-pass-123")}
    # Гурван үүрэг (005_three_roles): менежер бүх ажлыг хийнэ, удирдлага харж экспортлоно, админ системийг
    for name, roles in (("manager", ["manager"]), ("manager2", ["manager"]), ("executive", ["executive"])):
        r = client.post("/api/v1/users", headers=_h(tok["admin"]),
                        json={"username": name, "password": f"{name}-pass-1", "roles": roles,
                              **({"branches": ["*"]} if "manager" in roles else {})})
        assert r.status_code == 201, r.text
        tok[name] = _login(client, name, f"{name}-pass-1")
    return tok


def _login(client, u, p):
    r = client.post("/api/v1/auth/token", data={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _upload(client, tok, ds, folder, mapping, force=False):
    files = {"file": ("transactions.csv", (folder / "transactions.csv").read_bytes(), "text/csv"),
             "calendar_file": ("calendar.csv", (folder / "calendar.csv").read_bytes(), "text/csv"),
             "inventory_file": ("inventory.csv", (folder / "inventory.csv").read_bytes(), "text/csv"),
             "price_file": ("prices.csv", (folder / "prices.csv").read_bytes(), "text/csv")}
    data = {"mapping": json.dumps(mapping), "date_format": "%Y-%m-%d", "force": str(force).lower(),
            "unit_conversions": json.dumps([{"product_id": "P005", "from": "хайрцаг", "to": "ширхэг", "factor": 12}])}
    return client.post(f"/api/v1/datasets/{ds}/versions", headers=_h(tok), files=files, data=data)


@pytest.fixture(scope="module")
def version(client, users, synthetic):
    st = users["manager"]
    ds = client.post("/api/v1/datasets", headers=_h(st), json={"name": "Синтетик", "source": "synthetic"}).json()["id"]
    prev = client.post(f"/api/v1/datasets/{ds}/preview", headers=_h(st),
                       files={"file": ("t.csv", (synthetic / "transactions.csv").read_bytes(), "text/csv")}).json()
    assert {k: v for k, v in prev["suggested_mapping"].items() if v} == MAPPING   # заавал биш хоосон талбар (order_status …) тоолохгүй

    bad = _upload(client, st, ds, synthetic, {k: v for k, v in MAPPING.items() if k != "qty"})
    assert bad.status_code == 422 and bad.json()["code"] == "missing_required_fields"   # UC-01 2а
    assert "qty" in bad.json()["details"]["missing"]

    r = _upload(client, st, ds, synthetic, MAPPING)
    assert r.status_code == 202, r.text
    vid, job = r.json()["version_id"], r.json()["job_id"]
    drain()
    assert client.get(f"/api/v1/jobs/{job}", headers=_h(st)).json()["status"] == "done"
    assert _upload(client, st, ds, synthetic, MAPPING).status_code == 409        # UC-01 4а: давхар checksum

    v = client.get(f"/api/v1/dataset-versions/{vid}", headers=_h(st)).json()
    assert v["status"] == "failed"                                              # DQ-01 «abc» блоклосон
    issues = client.get(f"/api/v1/dataset-versions/{vid}/issues?severity=blocking", headers=_h(st)).json()["items"]
    assert [i["rule_id"] for i in issues] == ["DQ-01"] and issues[0]["original_value"] == "nan"
    r = client.patch(f"/api/v1/issues/{issues[0]['id']}", headers=_h(st),
                     json={"action": "excluded", "reason": "хэмжээ тоо биш тул мөрийг хасав"})
    assert r.status_code == 200 and r.json()["original_value"] == "nan"
    client.post(f"/api/v1/dataset-versions/{vid}/apply", headers=_h(st))
    drain()
    q = client.get(f"/api/v1/dataset-versions/{vid}/quality", headers=_h(st)).json()
    assert q["usable"] and q["version"]["status"] == "validated"
    states = set().union(*[s["states"] for s in q["by_series"]])
    assert {"sold", "closed", "stockout", "open_no_sale", "unknown"} <= states    # FR-D5: 0 болгоогүй
    return vid


def test_full_flow(client, users, version):
    rs, an = users["manager"], users["manager"]
    d = client.get("/api/v1/experiments/defaults", headers=_h(rs)).json()
    assert d["targets"]["sales"] == "Борлуулалтын таамаглал"
    body = {"name": "Үндсэн S", "dataset_version_id": version, "target": "sales",
            "protocol": {"sample": {"max_series": 10}}}
    e = client.post("/api/v1/experiments", headers=_h(rs), json=body).json()
    eid = e["id"]
    assert client.put(f"/api/v1/experiments/{eid}/protocol", headers=_h(rs),
                      json={"protocol": {"sample": {"max_series": 8}}}).status_code == 200    # draft: засаж болно
    assert client.post(f"/api/v1/experiments/{eid}/lock", headers=_h(rs)).status_code == 409
    r = client.post(f"/api/v1/experiments/{eid}/validate", headers=_h(rs))
    assert r.status_code == 202
    r = client.put(f"/api/v1/experiments/{eid}/protocol", headers=_h(rs), json={"protocol": {}})
    assert r.status_code == 409 and r.json()["code"] == "experiment_locked"            # UC-04 6а
    drain()
    e = client.get(f"/api/v1/experiments/{eid}", headers=_h(rs)).json()
    assert e["status"] == "validation_done" and e["protocol_hash"]
    sel = client.get(f"/api/v1/experiments/{eid}/selection", headers=_h(rs)).json()
    assert {str(k) for k in sel["summary"]} == {"1", "3", "12"}                       # сар, улирал, жил
    assert client.post(f"/api/v1/experiments/{eid}/test", headers=_h(rs)).status_code == 409   # түгжээгүй
    lk = client.post(f"/api/v1/experiments/{eid}/lock", headers=_h(rs)).json()
    assert lk["status"] == "locked" and len(lk["selection_hash"]) == 64
    assert client.post(f"/api/v1/experiments/{eid}/test", headers=_h(rs)).status_code == 202
    again = client.post(f"/api/v1/experiments/{eid}/test", headers=_h(rs))
    assert again.status_code == 409 and again.json()["code"] == "test_already_run"      # §4.8 дүрэм 7
    drain()
    assert client.get(f"/api/v1/experiments/{eid}", headers=_h(rs)).json()["status"] == "test_done"

    rep = client.get(f"/api/v1/experiments/{eid}/report", headers=_h(rs)).json()
    assert rep["sample"]["included"] == 8 and len(rep["test"]) == 3
    assert {"failures", "runs", "validation"} <= set(rep)
    assert all(t["selected_MASE"]["n"] > 0 for t in rep["test"])
    xl = client.get(f"/api/v1/experiments/{eid}/report?format=xlsx", headers=_h(rs))
    assert xl.status_code == 200 and "Тест" in pd.ExcelFile(io.BytesIO(xl.content)).sheet_names

    # UC-03: таамаглал харах (FR-F2: зорилтын нэр, нэгж, эхлэл, run үргэлж)
    series = client.get(f"/api/v1/forecasts/series?experiment_id={eid}", headers=_h(an)).json()
    sid = series[0]["series_id"]
    fc = client.get(f"/api/v1/forecasts?experiment_id={eid}&series={sid}&horizon=12", headers=_h(an)).json()
    assert fc["target_label"] == "Борлуулалтын таамаглал" and fc["unit"] and fc["run_id"] and fc["origin_date"]
    assert len(fc["forecast"]) == 12 and fc["history"] and fc["split"] == "live"
    assert fc["interval"]["available"] == (fc["forecast"][0]["q_lo"] is not None)        # FR-E4
    assert all({"month", "value"} <= set(h) for h in fc["history"])                  # сарын түүх
    assert fc["data_states"]                                                           # өдрийн төлөв (FR-F3) нэгтгэлээр
    test_fc = client.get(f"/api/v1/forecasts?experiment_id={eid}&series={sid}&horizon=1&split=test",
                         headers=_h(an)).json()
    assert len(test_fc["origins"]) == 12 and test_fc["actual"]          # тест 12 сар, сар бүр эхлэл

    # UC-06: залруулга — анхны таамаглал өөрчлөгдөхгүй (FR-G1, §4.8 дүрэм 10)
    first = fc["forecast"][0]
    r = client.post("/api/v1/adjustments", headers=_h(an), json={
        "run_id": fc["run_id"], "series_id": sid, "target_date": first["target_date"],
        "adjusted_value": first["y_hat"] + 5, "reason": "урамшуулал төлөвлөсөн"})
    assert r.status_code == 201 and r.json()["original_value"] == pytest.approx(first["y_hat"])
    fc2 = client.get(f"/api/v1/forecasts?experiment_id={eid}&series={sid}&horizon=12", headers=_h(an)).json()
    assert fc2["forecast"][0]["y_hat"] == pytest.approx(first["y_hat"])
    assert fc2["adjusted"][0]["adjusted_value"] == pytest.approx(first["y_hat"] + 5)
    fva = client.get(f"/api/v1/adjustments/value-added?experiment_id={eid}", headers=_h(an)).json()
    assert fva["fva_mae"] is None and "хувилбар" in fva["message"]                    # бодит утга хараахан алга

    # UC-05, FR-F4
    cmp_ = client.get(f"/api/v1/forecasts/compare?experiment_id={eid}&series={sid}", headers=_h(an)).json()
    assert len(cmp_["runs"]) == len(d["protocol"]["models"])                         # протоколын загвар бүр (8)
    assert len(cmp_["origins"]) == 12                                                  # validation-ийн 12 эхлэл
    ex = client.get(f"/api/v1/forecasts/{fc['run_id']}/explain?series={sid}", headers=_h(an)).json()
    assert ex["feature_behaviour"]["available"] is False

    # UC-07: экспорт — зорилтын нэр мөр бүрд
    csv = client.get(f"/api/v1/export/forecasts?experiment_id={eid}&format=csv", headers=_h(an))
    df = pd.read_csv(io.StringIO(csv.content.decode("utf-8-sig")))
    assert (df["target_label"] == "Борлуулалтын таамаглал").all() and df["adjusted_value"].notna().sum() == 1
    xl = client.get(f"/api/v1/export/forecasts?experiment_id={eid}&format=xlsx", headers=_h(users["executive"]))
    assert xl.status_code == 200

    # FR-G3: аудит
    aud = client.get("/api/v1/audit?limit=500", headers=_h(users["admin"])).json()
    actions = {a["action"] for a in aud}
    assert {"protocol_change_rejected", "test_rejected", "lock_selection", "start_test",
            "resolve_issue", "export_forecasts"} <= actions


def test_permission_matrix(client, users, version):
    """Хүснэгт 4.11 (гурван үүрэг)."""
    h = {k: _h(v) for k, v in users.items()}
    assert client.get("/api/v1/experiments").status_code == 401
    ex = h["executive"]
    assert client.post("/api/v1/experiments", headers=ex, json={}).status_code in (403, 422)
    assert client.post("/api/v1/experiments", headers=ex,
                       json={"name": "x", "dataset_version_id": version, "target": "sales"}).status_code == 403
    assert client.post("/api/v1/adjustments", headers=ex, json={
        "run_id": 1, "series_id": 1, "target_date": "2026-10-01", "adjusted_value": 1, "reason": "abc"}).status_code == 403
    assert client.get(f"/api/v1/dataset-versions/{version}/quality", headers=ex).status_code == 200   # удирдлага харна
    assert client.get("/api/v1/experiments", headers=ex).status_code == 200
    assert client.post("/api/v1/datasets", headers=ex, json={"name": "z"}).status_code == 403
    assert client.get("/api/v1/users", headers=h["manager"]).status_code == 403
    assert client.get("/api/v1/audit", headers=h["admin"]).status_code == 200
    assert client.get("/api/v1/experiments", headers=h["admin"]).status_code == 403      # админ таамаглал харахгүй
    assert client.get("/api/v1/export/forecasts?experiment_id=1", headers=h["admin"]).status_code == 403


def test_cancel_and_retry_validation(client, users, version):
    rs = _h(users["manager"])
    eid = client.post("/api/v1/experiments", headers=rs, json={
        "name": "Цуцлах", "dataset_version_id": version, "target": "demand",
        "protocol": {"sample": {"max_series": 3}, "models": [{"name": "ma", "params": {"window": 3}},   # суурь заавал
                                                            {"name": "sba", "params": {"alpha": 0.1}}]}}).json()["id"]
    job = client.post(f"/api/v1/experiments/{eid}/validate", headers=rs).json()["job_id"]
    assert client.post(f"/api/v1/jobs/{job}/cancel", headers=rs).json()["cancel_requested"]
    assert client.get(f"/api/v1/jobs/{job}", headers=rs).json()["status"] == "cancelled"
    assert client.get(f"/api/v1/jobs/{job}", headers=_h(users["manager2"])).status_code == 403   # эзэмшигч л
    drain()
    e = client.get(f"/api/v1/experiments/{eid}", headers=rs).json()
    assert e["status"] == "validating"                                  # протокол түгжигдсэн хэвээр
    assert client.post(f"/api/v1/experiments/{eid}/validate", headers=rs).status_code == 202   # ижил протоколоор дахин
    drain()
    e2 = client.get(f"/api/v1/experiments/{eid}", headers=rs).json()
    assert e2["status"] == "validation_done" and e2["protocol_hash"] == e["protocol_hash"]
    assert e2["target_label"] == "Эрэлтийн таамаглал"



def test_manager_without_branches(client, users, version, synthetic, database):
    """Салбаргүй менежер: PATCH-ээр хоосон салбар оноох боломжгүй; DB-д ийм болсон ч импорт 500 биш, ойлгомжтой 403."""
    from fcsys.db import connect
    h = _h(users["admin"])
    uid = next(u["id"] for u in client.get("/api/v1/users", headers=h).json() if u["username"] == "manager2")
    r = client.patch(f"/api/v1/users/{uid}", headers=h, json={"branches": []})
    assert r.status_code == 422 and r.json()["code"] == "branches_required", r.text
    with connect(database["app"]) as conn:          # хуучин хувилбараар хадгалагдсан хоосон салбар
        conn.execute("UPDATE governance.app_user SET branches='{}' WHERE id=%s", (uid,))
        conn.commit()
    try:
        ds = client.post("/api/v1/datasets", headers=_h(users["manager2"]), json={"name": "Салбаргүй"}).json()["id"]
        r = _upload(client, users["manager2"], ds, synthetic, {k: v for k, v in MAPPING.items() if k != "branch_id"})
        assert r.status_code == 403 and r.json()["code"] == "no_branches", r.text
    finally:
        with connect(database["app"]) as conn:
            conn.execute("UPDATE governance.app_user SET branches='{*}' WHERE id=%s", (uid,))
            conn.commit()
