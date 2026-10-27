"""Залруулга, FVA, экспорт, ажил, хэрэглэгч, аудит, архив (UC-06, UC-07, UC-09)."""
from __future__ import annotations

import datetime as dt
import io

import pandas as pd
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...db import audit, jsonb
from ...engine.grid import TARGET_LABELS
from ...engine.monthly import monthly_target
from ...engine.jobs import maybe_finalize
from ...engine.store import load_daily
from ..core import ROLES, ApiError, require_monthly, assert_branch, current_user, get_conn, hash_password, not_found, require, scope_sql

router = APIRouter()


# ---------------- Залруулга (FR-G1, FR-G2) ----------------
class AdjustmentIn(BaseModel):
    run_id: int
    series_id: int
    target_date: dt.date
    adjusted_value: float = Field(ge=0)
    reason: str = Field(min_length=3, max_length=500)


@router.post("/adjustments", status_code=201, tags=["governance"])
def create_adjustment(body: AdjustmentIn, conn=Depends(get_conn), user=Depends(require("adjust"))):
    """original_value-г сервер өөрөө forecast_value-аас бичнэ; forecast_value өөрчлөгдөхгүй."""
    s = conn.execute("SELECT branch_id FROM curated.series WHERE id=%s", (body.series_id,)).fetchone()
    if not s:
        raise not_found("Цуваа", body.series_id)
    assert_branch(user, s["branch_id"])
    fv = conn.execute(
        "SELECT y_hat FROM forecast.forecast_value WHERE run_id=%s AND series_id=%s AND split='live' AND target_date=%s "
        "ORDER BY origin_date DESC LIMIT 1", (body.run_id, body.series_id, body.target_date)).fetchone()
    if not fv:
        raise ApiError(404, "no_live_forecast", "Энэ огноонд гаргасан (live) таамаглал алга")
    row = conn.execute(
        "INSERT INTO governance.forecast_adjustment (run_id, series_id, target_date, original_value, adjusted_value, "
        "reason, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (body.run_id, body.series_id, body.target_date, fv["y_hat"], body.adjusted_value, body.reason, user["id"])
    ).fetchone()
    audit(conn, user["id"], "create", "forecast_adjustment", row["id"],
          {"original_value": fv["y_hat"], "adjusted_value": body.adjusted_value})
    return row


@router.get("/adjustments", tags=["governance"])
def list_adjustments(run_id: int | None = None, series_id: int | None = None, conn=Depends(get_conn),
                     user=Depends(require("forecast_view"))):
    q = ("SELECT a.*, u.username FROM governance.forecast_adjustment a JOIN governance.app_user u ON u.id=a.user_id "
         "WHERE (%s::bigint IS NULL OR a.run_id=%s) AND (%s::bigint IS NULL OR a.series_id=%s) ORDER BY a.created_at DESC "
         "LIMIT 500")
    return conn.execute(q, (run_id, run_id, series_id, series_id)).fetchall()


@router.get("/adjustments/value-added", tags=["governance"])
def value_added(experiment_id: int, conn=Depends(get_conn), user=Depends(require("adjust"))):
    """FVA = L_model − L_adjusted (MAE), бодит утга нь ижил өгөгдлийн багцын хожмын хувилбараас.
    Эерэг FVA = залруулга алдааг бууруулсан."""
    e = conn.execute("SELECT e.*, v.dataset_id, v.version_no FROM experiment.experiment e JOIN raw.dataset_version v "
                     "ON v.id=e.dataset_version_id WHERE e.id=%s", (experiment_id,)).fetchone()
    if not e:
        raise not_found("Туршилт", experiment_id)
    require_monthly(e)
    adj = conn.execute(
        "SELECT DISTINCT ON (a.run_id, a.series_id, a.target_date) a.* FROM governance.forecast_adjustment a "
        "JOIN experiment.run r ON r.run_id=a.run_id WHERE r.experiment_id=%s "
        "ORDER BY a.run_id, a.series_id, a.target_date, a.created_at DESC", (experiment_id,)).fetchall()
    later = conn.execute("SELECT id, version_no FROM raw.dataset_version WHERE dataset_id=%s AND version_no > %s "
                         "AND status='validated' ORDER BY version_no DESC LIMIT 1", (e["dataset_id"], e["version_no"])).fetchone()
    base = {"n_adjustments": len(adj), "fva_mae": None, "n_pairs": 0}
    if not adj:
        return {**base, "message": "Залруулга бүртгэгдээгүй"}
    if not later:
        return {**base, "message": "Бодит утга агуулсан хожмын хувилбар алга — FVA-г бодит борлуулалт ирсний дараа хэмжинэ"}
    sids = sorted({a["series_id"] for a in adj})
    later_max = conn.execute("SELECT date_max FROM raw.dataset_version WHERE id=%s", (later["id"],)).fetchone()["date_max"]
    daily = load_daily(conn, later["id"], sids)
    pairs = []
    for a in adj:
        d = daily.get(a["series_id"])
        if d is None:
            continue
        y = monthly_target(d, e["target"], later_max)      # бодит сарын утга (бүтэн сар л)
        yv = y.get(pd.Timestamp(a["target_date"]))
        if yv is None or pd.isna(yv):
            continue
        pairs.append((abs(a["original_value"] - yv), abs(a["adjusted_value"] - yv)))
    if not pairs:
        return {**base, "message": "Залруулсан сард ажиглагдсан (бүтэн) бодит утга алга"}
    l_model = sum(p[0] for p in pairs) / len(pairs)
    l_adj = sum(p[1] for p in pairs) / len(pairs)
    return {"n_adjustments": len(adj), "n_pairs": len(pairs), "mae_model": l_model, "mae_adjusted": l_adj,
            "fva_mae": l_model - l_adj, "actuals_version_no": later["version_no"]}


# ---------------- Экспорт (FR-X1) ----------------
@router.get("/export/forecasts", tags=["export"])
def export_forecasts(experiment_id: int, split: str = "live", format: str = Query("csv", pattern="^(csv|xlsx)$"),
                     conn=Depends(get_conn), user=Depends(require("export"))):
    e = conn.execute("SELECT e.*, v.version_no, v.sha256, d.name AS dataset FROM experiment.experiment e "
                     "JOIN raw.dataset_version v ON v.id=e.dataset_version_id JOIN raw.dataset d ON d.id=v.dataset_id "
                     "WHERE e.id=%s", (experiment_id,)).fetchone()
    if not e:
        raise not_found("Туршилт", experiment_id)
    require_monthly(e)
    rows = conn.execute(
        "SELECT s.product_id, s.product_name, s.product_category, s.branch_id, s.unit, r.run_id, r.model, "
        "fv.origin_date AS last_known_month, fv.h AS month_ahead, fv.target_date AS target_month, fv.y_hat, fv.q_lo, fv.q_hi, "
        "(SELECT a.adjusted_value FROM governance.forecast_adjustment a WHERE a.run_id=fv.run_id AND "
        " a.series_id=fv.series_id AND a.target_date=fv.target_date ORDER BY a.created_at DESC LIMIT 1) AS adjusted_value "
        "FROM forecast.forecast_value fv JOIN experiment.run r ON r.run_id=fv.run_id "
        "JOIN curated.series s ON s.id=fv.series_id "
        "JOIN experiment.model_selection ms ON ms.experiment_id=r.experiment_id AND ms.series_id=fv.series_id "
        "JOIN experiment.run vr ON vr.run_id=ms.run_id AND vr.model=r.model AND vr.params=r.params "
        "WHERE r.experiment_id=%s AND fv.split=%s AND ms.horizon=12 " + scope_sql(user)[0] +
        " ORDER BY coalesce(s.product_name, s.product_id), s.branch_id, fv.origin_date, fv.h",
        [experiment_id, split, *scope_sql(user)[1]]).fetchall()
    df = pd.DataFrame(rows)
    label = TARGET_LABELS[e["target"]]
    periods = pd.DataFrame()
    if not df.empty:
        # Хугацааны нийлбэр (тэгшитгэл 2.2): сар = 1, улирал = 3, жил = 12 сарын цэгэн таамаглалын нийлбэр.
        # Интервалын хязгаарыг нэмж хугацааны интервал гэж үзэхгүй.
        df["final_value"] = df["adjusted_value"].fillna(df["y_hat"])
        key = ["product_id", "product_name", "product_category", "branch_id", "unit", "last_known_month"]
        recs = []
        for k, g in df.groupby(key, dropna=False, sort=False):
            g = g.sort_values("month_ahead")
            r = dict(zip(key, k))
            for n, lbl in ((1, "Сар"), (3, "Улирал"), (12, "Жил")):
                r[f"{lbl} (таамаглал)"] = float(g["y_hat"].iloc[:n].sum()) if len(g) >= n else None
                r[f"{lbl} (залруулсан)"] = float(g["final_value"].iloc[:n].sum()) if len(g) >= n else None
            recs.append(r)
        periods = pd.DataFrame(recs)
        df.insert(0, "target_label", label)           # FR-F2: зорилтын нэр мөр бүрд
        df.insert(1, "target", e["target"])
        df["experiment_id"] = e["id"]
        df["data_version"] = f"{e['dataset']} v{e['version_no']}"
        df["protocol_hash"] = e["protocol_hash"]
    audit(conn, user["id"], "export_forecasts", "experiment", experiment_id, {"split": split, "format": format,
                                                                             "rows": len(df)})
    fname = f"forecast_{e['target']}_exp{experiment_id}_{split}"
    if format == "csv":
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        return StreamingResponse(io.BytesIO(buf.getvalue().encode("utf-8-sig")), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'})
    out = io.BytesIO()
    meta = pd.DataFrame([("Зорилт", label), ("Туршилт", f"#{e['id']} {e['name']}"), ("Хуваалт", split),
                         ("Өгөгдөл", f"{e['dataset']} v{e['version_no']}"), ("sha256", e["sha256"]),
                         ("protocol_hash", e["protocol_hash"]), ("selection_hash", e["selection_hash"]),
                         ("Экспортолсон", f"{user['username']} {dt.datetime.now():%Y-%m-%d %H:%M}"),
                         ("Тайлбар", "y_hat = загварын анхны таамаглал; adjusted_value = хэрэглэгчийн залруулга (тусдаа)")],
                        columns=["Талбар", "Утга"])
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        meta.to_excel(xw, sheet_name="Мэдээлэл", index=False)
        df.to_excel(xw, sheet_name="Сар бүрээр", index=False)
        periods.to_excel(xw, sheet_name="Сар, улирал, жилийн нийлбэр", index=False)
    return StreamingResponse(io.BytesIO(out.getvalue()),
                             media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{fname}.xlsx"'})


# ---------------- Ажил (FR-M5) ----------------
def _job_for_owner(conn, job_id: int, user: dict) -> dict:
    j = conn.execute("SELECT * FROM governance.job WHERE id=%s", (job_id,)).fetchone()
    if not j:
        raise not_found("Ажил", job_id)
    if j["created_by"] != user["id"] and "admin" not in user["roles"]:
        raise ApiError(403, "forbidden", "Зөвхөн ажлын эзэмшигч харна")
    return j


@router.get("/jobs/{job_id}", tags=["jobs"])
def get_job(job_id: int, conn=Depends(get_conn), user=Depends(current_user)):
    j = _job_for_owner(conn, job_id, user)
    kids = conn.execute("SELECT status, count(*) AS n FROM governance.job WHERE parent_id=%s AND type='forecast_batch' "
                        "GROUP BY status", (job_id,)).fetchall()
    counts = {k["status"]: k["n"] for k in kids}
    total = sum(counts.values())
    done = counts.get("done", 0) + counts.get("failed", 0) + counts.get("cancelled", 0)
    j["children"] = counts
    j["percent"] = 100 if j["status"] == "done" else (round(100 * done / total) if total else None)
    return j


@router.get("/jobs", tags=["jobs"])
def my_jobs(limit: int = 30, conn=Depends(get_conn), user=Depends(current_user)):
    return conn.execute("SELECT id, type, status, progress, error, payload, created_at, finished_at FROM governance.job "
                        "WHERE parent_id IS NULL AND created_by=%s ORDER BY id DESC LIMIT %s", (user["id"], limit)).fetchall()


@router.post("/jobs/{job_id}/cancel", tags=["jobs"])
def cancel_job(job_id: int, conn=Depends(get_conn), user=Depends(current_user)):
    j = _job_for_owner(conn, job_id, user)
    if j["status"] in ("done", "failed", "cancelled"):
        raise ApiError(409, "job_finished", f"Ажил аль хэдийн '{j['status']}' төлөвтэй")
    conn.execute("UPDATE governance.job SET cancel_requested=true WHERE id=%s OR parent_id=%s", (job_id, job_id))
    conn.execute("UPDATE governance.job SET status='cancelled', finished_at=now() WHERE (id=%s OR parent_id=%s) "
                 "AND status='queued'", (job_id, job_id))
    if j["type"] in ("validate", "test") and j["status"] == "running":
        maybe_finalize(conn, job_id)
    audit(conn, user["id"], "cancel", "job", job_id, {})
    return {"cancel_requested": True}


# ---------------- Хэрэглэгч, аудит, архив (FR-A1, FR-A2, FR-G3) ----------------
class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$")
    full_name: str = ""
    password: str = Field(min_length=8)
    roles: list[str]
    branches: list[str] = Field(default_factory=lambda: ["*"], description="Менежерийн салбар; '*' = бүгд")


class UserPatch(BaseModel):
    full_name: str | None = None
    password: str | None = Field(None, min_length=8)
    roles: list[str] | None = None
    branches: list[str] | None = None
    is_active: bool | None = None


def _check_roles(roles: list[str]) -> None:
    bad = [r for r in roles if r not in ROLES]
    if bad:
        raise ApiError(422, "invalid_roles", f"Үл мэдэгдэх үүрэг: {bad}", {"allowed": list(ROLES)})


@router.get("/users", tags=["admin"])
def list_users(conn=Depends(get_conn), user=Depends(require("admin"))):
    return conn.execute("SELECT id, username, full_name, roles, branches, is_active, created_at FROM governance.app_user "
                        "ORDER BY id").fetchall()


@router.get("/branches", tags=["admin"])
def list_branches(conn=Depends(get_conn), user=Depends(require("series_view"))):
    """Өгөгдөлд байгаа салбарын код (админ менежерт оноох, удирдлага шүүх)."""
    return [r["branch_id"] for r in conn.execute(
        "SELECT DISTINCT branch_id FROM curated.series ORDER BY 1").fetchall()]


@router.post("/users", status_code=201, tags=["admin"])
def create_user(body: UserIn, conn=Depends(get_conn), user=Depends(require("admin"))):
    _check_roles(body.roles)
    if conn.execute("SELECT 1 FROM governance.app_user WHERE username=%s", (body.username,)).fetchone():
        raise ApiError(409, "duplicate_username", "Ийм нэвтрэх нэр бүртгэлтэй")
    if "manager" in body.roles and not body.branches:
        raise ApiError(422, "branches_required", "Менежерт дор хаяж нэг салбар оноох шаардлагатай (эсвэл «Бүх салбар»)")
    row = conn.execute("INSERT INTO governance.app_user (username, full_name, password_hash, roles, branches) "
                       "VALUES (%s,%s,%s,%s,%s) RETURNING id, username, full_name, roles, branches, is_active",
                       (body.username, body.full_name, hash_password(body.password), body.roles, body.branches)).fetchone()
    audit(conn, user["id"], "create", "app_user", row["id"], {"roles": body.roles, "branches": body.branches})
    return row


@router.patch("/users/{uid}", tags=["admin"])
def update_user(uid: int, body: UserPatch, conn=Depends(get_conn), user=Depends(require("admin"))):
    if body.roles is not None:
        _check_roles(body.roles)
    row = conn.execute(
        "UPDATE governance.app_user SET full_name=coalesce(%s, full_name), roles=coalesce(%s, roles), "
        "branches=coalesce(%s, branches), is_active=coalesce(%s, is_active), password_hash=coalesce(%s, password_hash) "
        "WHERE id=%s RETURNING id, username, full_name, roles, branches, is_active",
        (body.full_name, body.roles, body.branches, body.is_active,
         hash_password(body.password) if body.password else None, uid)
    ).fetchone()
    if not row:
        raise not_found("Хэрэглэгч", uid)
    audit(conn, user["id"], "edit", "app_user", uid, {k: v for k, v in body.model_dump().items()
                                                     if v is not None and k != "password"})
    return row


@router.get("/audit", tags=["admin"])
def audit_log(limit: int = Query(200, le=2000), object_type: str | None = None, conn=Depends(get_conn),
              user=Depends(require("admin"))):
    return conn.execute("SELECT a.*, u.username FROM governance.audit_log a LEFT JOIN governance.app_user u "
                        "ON u.id=a.user_id WHERE (%s::text IS NULL OR a.object_type=%s) ORDER BY a.id DESC LIMIT %s",
                        (object_type, object_type, limit)).fetchall()


@router.post("/dataset-versions/{vid}/archive", tags=["admin"])
def archive_version(vid: int, conn=Depends(get_conn), user=Depends(require("admin"))):
    row = conn.execute("UPDATE raw.dataset_version SET archived_at=coalesce(archived_at, now()) WHERE id=%s RETURNING id",
                       (vid,)).fetchone()
    if not row:
        raise not_found("Өгөгдлийн хувилбар", vid)
    audit(conn, user["id"], "archive", "dataset_version", vid, {})
    return {"archived": True}
