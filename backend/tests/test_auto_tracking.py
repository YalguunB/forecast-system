"""Нэг товшилтын урсгал (validate?auto=true), хосолсон арга (combo), бодит гүйцэтгэл (/forecasts/tracking; FR-05, FR-15).

Өгөгдөл: 4 бараа × 39 сар, өдөр бүр, улиралтай. Эхлээд 36 сарыг оруулж таамаглана; дараа нь 39 сарыг ижил багцад
оруулж, таамагласан эхний 3 сарыг бодит борлуулалттай харьцуулна. Хүлээгдэх утгыг системийн кодоос тусад нь (pandas) тооцно."""
import io
import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from fcsys.api.core import hash_password
from fcsys.engine.models import FitContext, make_model
from fcsys.engine.worker import drain

MAPPING = {"txn_date": "sale_date", "product_id": "item", "branch_id": "store", "qty": "quantity", "unit": "uom",
           "txn_id": "receipt_no"}
CUT = "2023-12-31"            # эхний файл: 2021-01 … 2023-12 (36 сар); хоёр дахь: … 2024-03 (39 сар)


def _sales() -> pd.DataFrame:
    rng = np.random.default_rng(11)
    days = pd.date_range("2021-01-01", "2024-03-31", freq="D")
    rows = []
    for k in range(4):
        lam = (8 + 4 * k) * (1 + 0.3 * np.sin(2 * np.pi * (days.dayofyear / 365.25) + k))
        qty = rng.poisson(lam) + 1                       # өдөр бүр ≥ 1 → бүх сар бүрэн
        rows.append(pd.DataFrame({"sale_date": days.strftime("%Y-%m-%d"), "item": f"T{k + 1:03d}", "store": "B01",
                                  "quantity": qty, "uom": "ширхэг"}))
    df = pd.concat(rows, ignore_index=True)
    df.insert(0, "receipt_no", [f"R{i:07d}" for i in range(len(df))])
    return df


@pytest.fixture(scope="module")
def ctx(database):
    from fcsys.api.main import app
    from fcsys.db import connect
    with connect(database["app"]) as conn:
        conn.execute("INSERT INTO governance.app_user (username, password_hash, roles, branches) "
                     "VALUES ('mgr_t', %s, '{manager}', '{*}') ON CONFLICT (username) DO NOTHING",
                     (hash_password("mgr-t-pass-1"),))
        conn.commit()
    with TestClient(app) as c:
        tok = c.post("/api/v1/auth/token", data={"username": "mgr_t", "password": "mgr-t-pass-1"}).json()["access_token"]
        yield {"c": c, "h": {"Authorization": f"Bearer {tok}"}, "db": database, "sales": _sales()}


def _upload(ctx, ds: int, df: pd.DataFrame) -> int:
    buf = io.BytesIO(df.to_csv(index=False).encode())
    r = ctx["c"].post(f"/api/v1/datasets/{ds}/versions", headers=ctx["h"],
                      files={"file": ("sales.csv", buf.getvalue(), "text/csv")},
                      data={"mapping": json.dumps(MAPPING), "date_format": "%Y-%m-%d"})
    assert r.status_code == 202, r.text
    drain(ctx["db"]["app"])
    vid = r.json()["version_id"]
    v = ctx["c"].get(f"/api/v1/dataset-versions/{vid}", headers=ctx["h"]).json()
    assert v["status"] == "validated", v
    return vid


def test_combo_is_mean_of_members():
    idx = pd.date_range("2019-01-01", periods=48, freq="MS")
    y = pd.Series(100 + 20 * np.sin(np.arange(48) * 2 * np.pi / 12) + np.arange(48), index=idx)
    fc = FitContext(series_id=1, origin=idx[-1], target="sales", horizon=12, seed=1)
    members = [{"name": "snaive", "params": {"m": 12}}, {"name": "ma", "params": {"window": 3}}]
    combo = make_model("combo", {"members": members})
    combo.fit(y, fc)
    out = combo.predict(fc)
    parts = []
    for m in members:
        mm = make_model(m["name"], m["params"])
        mm.fit(y, fc)
        parts.append(mm.predict(fc)["y_hat"].values)
    assert np.allclose(out["y_hat"].values, np.mean(parts, axis=0))
    assert out["q_lo"].isna().all()                       # интервалгүй бүрэлдэхүүн → интервал зохиохгүй
    with pytest.raises(AssertionError):                   # алдагдлын хамгаалалт бүрэлдэхүүнээр дамжина
        combo.fit(y, FitContext(series_id=1, origin=idx[-2], target="sales", horizon=12, seed=1))
    with pytest.raises(ValueError):
        make_model("combo", {"members": [{"name": "combo"}]}).fit(y, fc)


def test_one_click_then_tracking(ctx):
    c, h, sales = ctx["c"], ctx["h"], ctx["sales"]
    ds = c.post("/api/v1/datasets", headers=h, json={"name": "Гүйцэтгэлийн тест", "source": "synthetic"}).json()["id"]
    v1 = _upload(ctx, ds, sales[sales.sale_date <= CUT])

    proto = c.get(f"/api/v1/experiments/defaults?dataset_version_id={v1}", headers=h).json()["protocol"]
    assert any(m["name"] == "combo" for m in proto["models"])
    proto["models"] = [m for m in proto["models"] if m["name"] in ("ma", "snaive", "ets", "combo")]
    e = c.post("/api/v1/experiments", headers=h, json={"name": "Нэг товшилт", "dataset_version_id": v1,
                                                       "target": "sales", "protocol": proto}).json()
    r = c.post(f"/api/v1/experiments/{e['id']}/validate?auto=true", headers=h)
    assert r.status_code == 202 and r.json()["auto"] is True
    drain(ctx["db"]["app"])
    done = c.get(f"/api/v1/experiments/{e['id']}", headers=h).json()
    assert done["status"] == "test_done"                  # турших → түгжих → шалгах → таамаглах, гар оролцоогүй
    assert done["selection_hash"] and done["test_job_id"]
    assert [j["type"] for j in done["jobs"]] == ["test", "validate"] and all(j["status"] == "done" for j in done["jobs"])
    assert c.post(f"/api/v1/experiments/{e['id']}/test", headers=h).status_code == 409   # тест нэг л удаа

    t0 = c.get(f"/api/v1/forecasts/tracking?experiment_id={e['id']}", headers=h).json()
    assert t0["available"] is False and t0["reason"] == "no_new_data"   # бодит утга алга → алдааг 0 гэж харуулахгүй

    _upload(ctx, ds, sales)                               # шинэ 3 сар (2024-01 … 2024-03) ижил багцад
    t = c.get(f"/api/v1/forecasts/tracking?experiment_id={e['id']}&horizon=12", headers=h).json()
    assert t["available"] and t["months_compared"] == 3 and t["months_total"] == 12
    assert [m["month"] for m in t["by_month"]] == ["2024-01-01", "2024-02-01", "2024-03-01"]
    new = sales[sales.sale_date > CUT].assign(m=lambda d: d.sale_date.str[:7])
    assert t["overall"]["actual"] == pytest.approx(float(new.quantity.sum()))             # бие даасан тооцоо
    for row in t["by_month"]:
        assert row["actual"] == pytest.approx(float(new[new.m == row["month"][:7]].quantity.sum()))
    assert len(t["items"]) == 4 and all(len(it["months"]) == 3 for it in t["items"])
    by_item = {it["product_id"]: it for it in t["items"]}
    for pid, it in by_item.items():
        act = new[new.item == pid].groupby("m").quantity.sum()
        f = np.array([x["forecast"] for x in it["months"]])
        assert it["score"]["wape"] == pytest.approx(float(np.abs(f - act.values).sum() / act.values.sum()))
    assert 0 < t["overall"]["wape"] < 0.3                 # улиралтай, тогтвортой цуваа
    assert t["system_overall"] is None                    # гараар засвар алга

    # Гараар зассан сар: эцсийн таамаглал нь засвар, системийн анхны дүн тусад нь
    it = t["items"][0]
    fc = c.get(f"/api/v1/forecasts?experiment_id={e['id']}&series={it['series_id']}&horizon=12", headers=h).json()
    a = c.post("/api/v1/adjustments", headers=h, json={"run_id": fc["run_id"], "series_id": it["series_id"],
                                                        "target_date": "2024-01-01", "adjusted_value": 0, "reason": "тест"})
    assert a.status_code == 201, a.text
    t2 = c.get(f"/api/v1/forecasts/tracking?experiment_id={e['id']}&horizon=12", headers=h).json()
    assert t2["system_overall"]["wape"] == pytest.approx(t["overall"]["wape"])
    assert t2["overall"]["wape"] > t2["system_overall"]["wape"]
    assert c.get(f"/api/v1/forecasts/tracking?experiment_id={e['id']}&horizon=5", headers=h).status_code == 422
