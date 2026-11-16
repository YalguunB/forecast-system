"""Таамаглал харах, харьцуулах, тайлбарлах (UC-03, UC-05; FR-F1–F4)."""
from __future__ import annotations

import datetime as dt

import pandas as pd
from fastapi import APIRouter, Depends, Query

from ...db import jsonb
from ...engine.grid import TARGET_LABELS
from ...engine.monthly import HORIZONS, PERIOD_LABELS, add_months, build_monthly, last_complete_month, period_totals
from ...engine.store import load_daily
from ..core import ApiError, assert_branch, get_conn, not_found, require, require_monthly, scope_sql

router = APIRouter(tags=["forecasts"])

STATE_LABELS = {"sold": "Борлуулалттай", "open_no_sale": "Нээлттэй, борлуулалтгүй", "stockout": "Нөөцгүй", "sold_out": "Дууссан", "stockout_est": "Нөөцгүй бололтой",
                "closed": "Хаалттай", "missing": "Бүртгэл дутуу", "unknown": "Тодорхойгүй"}


def _exp(conn, eid: int) -> dict:
    e = conn.execute("SELECT e.*, v.date_max, v.version_no, d.name AS dataset FROM experiment.experiment e "
                     "JOIN raw.dataset_version v ON v.id=e.dataset_version_id JOIN raw.dataset d ON d.id=v.dataset_id "
                     "WHERE e.id=%s", (eid,)).fetchone()
    if not e:
        raise not_found("Туршилт", eid)
    require_monthly(e)
    return e


def _series(conn, sid: int) -> dict:
    s = conn.execute("SELECT * FROM curated.series WHERE id=%s", (sid,)).fetchone()
    if not s:
        raise not_found("Цуваа", sid)
    return s


def _run_for(conn, eid: int, sid: int, horizon: int, split: str, run_id: int | None) -> dict:
    if run_id:
        r = conn.execute("SELECT * FROM experiment.run WHERE run_id=%s AND experiment_id=%s", (run_id, eid)).fetchone()
        if not r:
            raise not_found("Run", run_id)
        return r
    sel = conn.execute("SELECT r.model, r.params FROM experiment.model_selection ms JOIN experiment.run r "
                       "ON r.run_id=ms.run_id WHERE ms.experiment_id=%s AND ms.series_id=%s AND ms.horizon=%s",
                       (eid, sid, horizon)).fetchone()
    if not sel:
        raise ApiError(404, "no_selection", "Энэ бараанд таамаглал гараагүй байна")
    r = conn.execute("SELECT * FROM experiment.run WHERE experiment_id=%s AND phase=%s AND model=%s AND params=%s",
                     (eid, split, sel["model"], jsonb(sel["params"]))).fetchone()
    if not r:
        raise ApiError(404, "no_run", "Таамаглал алга")
    return r


@router.get("/forecasts/series")
def experiment_series(experiment_id: int, conn=Depends(get_conn, scope="function"), user=Depends(require("forecast_view"))):
    rows = conn.execute(
        "SELECT i.series_id, s.product_id, s.product_name, s.branch_id, s.unit, p.class, p.zero_share FROM experiment.series_sample_item i "
        "JOIN experiment.series_sample ss ON ss.id=i.sample_id JOIN curated.series s ON s.id=i.series_id "
        "LEFT JOIN curated.series_profile p ON p.experiment_id=ss.experiment_id AND p.series_id=i.series_id "
        "WHERE ss.experiment_id=%s AND i.included" + scope_sql(user)[0] +
        " ORDER BY coalesce(s.product_name, s.product_id), s.branch_id", [experiment_id, *scope_sql(user)[1]]).fetchall()
    sel = conn.execute("SELECT ms.series_id, ms.horizon, r.model FROM experiment.model_selection ms "
                       "JOIN experiment.run r ON r.run_id=ms.run_id WHERE ms.experiment_id=%s", (experiment_id,)).fetchall()
    m: dict = {}
    for r in sel:
        m.setdefault(r["series_id"], {})[r["horizon"]] = r["model"]
    for r in rows:
        r["selected"] = m.get(r["series_id"], {})
    return rows


def _month_rows(table, start=None, end=None, after=None):
    out = []
    for m, r in table.iterrows():
        if (start is not None and m < start) or (end is not None and m > end):
            continue
        out.append({"month": m.date(), "value": None if pd.isna(r["y"]) else float(r["y"]),
                    "reason": r["reason"] if pd.isna(r["y"]) else None,
                    "n_gap": int(r["n_gap"]), "n_stockout": int(r["n_stockout"]),
                    **({"after_origin": bool(m > after)} if after is not None else {})})
    return out


@router.get("/forecasts")
def get_forecast(experiment_id: int, series: int, horizon: int = Query(12), split: str = Query("live"),
                 run_id: int | None = None, origin_date: dt.date | None = None, history_months: int = Query(36, le=240),
                 conn=Depends(get_conn, scope="function"), user=Depends(require("forecast_view"))):
    """FR-F1, FR-F2, FR-04: сарын таамаглал ба хугацааны (сар, улирал, жил) нийлбэр. Хариу нь зорилтын нэр,
    нэгж, эхлэл, run-ийн мэдээллийг үргэлж агуулна."""
    if horizon not in HORIZONS or split not in ("validation", "test", "live"):
        raise ApiError(422, "invalid_params", "Хугацаа буруу байна")
    e = _exp(conn, experiment_id)
    s = _series(conn, series)
    assert_branch(user, s["branch_id"])
    run = _run_for(conn, experiment_id, series, horizon, split, run_id)
    origins = [r["origin_date"] for r in conn.execute(
        "SELECT DISTINCT origin_date FROM forecast.forecast_value WHERE run_id=%s AND series_id=%s AND split=%s "
        "ORDER BY 1", (run["run_id"], series, split)).fetchall()]
    if split != "live":   # өнгөрсөнд: зөвхөн бүтэн хугацаа ажиглагдсан эхлэл (хэмжүүр тэдгээрт л бий)
        last = last_complete_month(e["date_max"])
        origins = [o for o in origins if add_months(o, horizon) <= last] or origins
    if not origins:
        raise ApiError(404, "no_forecast", "Энэ бараанд таамаглал алга")
    origin = origin_date if origin_date in origins else origins[-1]
    fc = conn.execute("SELECT h, target_date, y_hat, q_lo, q_hi FROM forecast.forecast_value WHERE run_id=%s AND "
                      "series_id=%s AND split=%s AND origin_date=%s AND h <= %s ORDER BY h",
                      (run["run_id"], series, split, origin, horizon)).fetchall()
    d = load_daily(conn, e["dataset_version_id"], [series])[series]
    table = build_monthly(d, e["target"], e["date_max"])
    o = pd.Timestamp(origin)
    history = _month_rows(table, add_months(o, -(history_months - 1)), o)
    actual = _month_rows(table, add_months(o, 1), add_months(o, horizon)) if split != "live" else []
    adjusted = conn.execute(
        "SELECT DISTINCT ON (a.target_date) a.target_date, a.adjusted_value, a.original_value, a.reason, a.created_at, "
        "u.username FROM governance.forecast_adjustment a JOIN governance.app_user u ON u.id=a.user_id "
        "WHERE a.run_id=%s AND a.series_id=%s ORDER BY a.target_date, a.created_at DESC", (run["run_id"], series)).fetchall()
    adj = {a["target_date"]: a["adjusted_value"] for a in adjusted}
    y_hat = [r["y_hat"] for r in fc]
    final = [adj.get(r["target_date"], r["y_hat"]) for r in fc]
    act = [a["value"] for a in actual]
    totals = {"forecast": period_totals(y_hat, (horizon,)).get(horizon),
              "adjusted": period_totals(final, (horizon,)).get(horizon) if adj else None,
              "actual": (sum(act) if act and len(act) == horizon and all(v is not None for v in act) else None),
              "months": horizon, "label": PERIOD_LABELS[horizon]}
    test_metrics = conn.execute(
        "SELECT em.metric, em.value, em.n_pairs, em.undefined_reason, r.model, r.role FROM forecast.error_metric em "
        "JOIN experiment.run r ON r.run_id=em.run_id WHERE r.experiment_id=%s AND r.phase='test' AND em.series_id=%s "
        "AND em.horizon=%s AND em.origin_date IS NULL AND (r.model=%s OR r.role='baseline') ORDER BY r.role, em.metric",
        (experiment_id, series, horizon, run["model"])).fetchall()
    runs = conn.execute("SELECT DISTINCT r.run_id, r.model, r.params, r.role FROM experiment.run r JOIN "
                        "forecast.forecast_value fv ON fv.run_id=r.run_id WHERE r.experiment_id=%s AND r.phase=%s "
                        "AND fv.series_id=%s ORDER BY r.run_id", (experiment_id, split, series)).fetchall()
    states = d["day_state"].value_counts().to_dict()
    return {
        "grain": "month",
        "target": e["target"], "target_label": TARGET_LABELS[e["target"]], "unit": s["unit"],
        "series": {"id": s["id"], "product_id": s["product_id"], "product_name": s["product_name"],
                   "product_category": s.get("product_category"), "branch_id": s["branch_id"]},
        "experiment": {"id": e["id"], "name": e["name"], "status": e["status"], "dataset": e["dataset"],
                       "version_no": e["version_no"], "protocol_hash": e["protocol_hash"]},
        "run_id": run["run_id"], "model": run["model"], "params": run["params"], "role": run["role"],
        "split": split, "origin_date": origin, "origins": origins, "horizon": horizon,
        "period_label": PERIOD_LABELS[horizon], "period_total": totals,
        "history": history, "actual": actual,
        "forecast": fc, "interval": {"available": any(r["q_lo"] is not None for r in fc), "level": 0.8,
                                     "note": "Интервал сар бүрд; хугацааны нийлбэрт интервал нэмэгдэхгүй."},
        "adjusted": adjusted, "test_metrics": test_metrics, "available_runs": runs,
        "data_states": {k: {"n": int(v), "label": STATE_LABELS[k]} for k, v in states.items()},
    }


@router.get("/forecasts/compare")
def compare(experiment_id: int, series: int, split: str = "validation", origin_date: dt.date | None = None,
            conn=Depends(get_conn, scope="function"), user=Depends(require("forecast_view"))):
    """FR-F4: загваруудыг ижил эхлэл дээр харьцуулна."""
    e = _exp(conn, experiment_id)
    s = _series(conn, series)
    assert_branch(user, s["branch_id"])
    origins = [r["origin_date"] for r in conn.execute(
        "SELECT DISTINCT fv.origin_date FROM forecast.forecast_value fv JOIN experiment.run r ON r.run_id=fv.run_id "
        "WHERE r.experiment_id=%s AND fv.series_id=%s AND fv.split=%s ORDER BY 1", (experiment_id, series, split)).fetchall()]
    if not origins:
        raise ApiError(404, "no_forecast", "Харьцуулах таамаглал алга")
    origin = origin_date if origin_date in origins else origins[0]
    rows = conn.execute(
        "SELECT r.run_id, r.model, r.params, r.role, fv.h, fv.target_date, fv.y_hat, fv.q_lo, fv.q_hi "
        "FROM forecast.forecast_value fv JOIN experiment.run r ON r.run_id=fv.run_id WHERE r.experiment_id=%s "
        "AND fv.series_id=%s AND fv.split=%s AND fv.origin_date=%s ORDER BY r.run_id, fv.h",
        (experiment_id, series, split, origin)).fetchall()
    metrics = conn.execute(
        "SELECT em.run_id, em.horizon, em.metric, em.value, em.undefined_reason FROM forecast.error_metric em "
        "JOIN experiment.run r ON r.run_id=em.run_id WHERE r.experiment_id=%s AND em.series_id=%s AND em.split=%s "
        "AND em.origin_date=%s AND em.metric IN ('WAPE','MAE','Bias','SUM_APE')", (experiment_id, series, split, origin)).fetchall()
    runs: dict = {}
    for r in rows:
        runs.setdefault(r["run_id"], {"run_id": r["run_id"], "model": r["model"], "params": r["params"],
                                      "role": r["role"], "forecast": [], "metrics": {}})["forecast"].append(
            {"h": r["h"], "target_date": r["target_date"], "y_hat": r["y_hat"], "q_lo": r["q_lo"], "q_hi": r["q_hi"]})
    for m in metrics:
        if m["run_id"] in runs:
            runs[m["run_id"]]["metrics"].setdefault(str(m["horizon"]), {})[m["metric"]] = {
                "value": m["value"], "undefined_reason": m["undefined_reason"]}
    d = load_daily(conn, e["dataset_version_id"], [series])[series]
    o = pd.Timestamp(origin)
    table = build_monthly(d, e["target"], e["date_max"])
    series_values = _month_rows(table, add_months(o, -23), add_months(o, 12), after=o)
    return {"target_label": TARGET_LABELS[e["target"]], "unit": s["unit"],
            "series": {"id": s["id"], "product_id": s["product_id"], "product_name": s["product_name"], "branch_id": s["branch_id"]},
            "split": split, "origin_date": origin, "origins": origins, "values": series_values,
            "runs": list(runs.values())}


@router.get("/forecasts/{run_id}/explain")
def explain(run_id: int, series: int, conn=Depends(get_conn, scope="function"), user=Depends(require("forecast_view"))):
    """FR-F3: алдааг өдрийн төлөвтэй холбож тайлбарлана. Шинжийн хувь нэмрийг «загварын зан төлөв»
    гэж л нэрлэнэ — шалтгаант нөлөө биш."""
    run = conn.execute("SELECT r.*, e.target, e.dataset_version_id FROM experiment.run r JOIN experiment.experiment e "
                       "ON e.id=r.experiment_id WHERE r.run_id=%s", (run_id,)).fetchone()
    if not run:
        raise not_found("Run", run_id)
    assert_branch(user, _series(conn, series)["branch_id"])
    d = load_daily(conn, run["dataset_version_id"], [series]).get(series)
    if d is None:
        raise not_found("Цуваа", series)
    per_origin = conn.execute(
        "SELECT origin_date, horizon, metric, value, undefined_reason FROM forecast.error_metric WHERE run_id=%s "
        "AND series_id=%s AND origin_date IS NOT NULL AND metric IN ('MAE','WAPE','Bias','SUM_AE') ORDER BY origin_date, horizon",
        (run_id, series)).fetchall()
    failures = conn.execute("SELECT origin_date, reason, fallback_model FROM forecast.run_failure WHERE run_id=%s "
                            "AND series_id=%s", (run_id, series)).fetchall()
    windows = []
    for o in sorted({r["origin_date"] for r in per_origin}):
        o_ts = pd.Timestamp(o)
        w = d[(d["day"] >= add_months(o_ts, 1)) & (d["day"] < add_months(o_ts, 13))]
        windows.append({"origin_date": o, "states": w["day_state"].value_counts().to_dict(),
                        "zero_days": int((w["sales_qty"] == 0).sum())})
    profile = conn.execute("SELECT * FROM curated.series_profile WHERE experiment_id=%s AND series_id=%s",
                           (run["experiment_id"], series)).fetchone()
    return {"run_id": run_id, "model": run["model"], "series_id": series, "per_origin": per_origin,
            "target_windows": windows, "failures": failures, "profile": profile,
            "state_labels": STATE_LABELS,
            "feature_behaviour": {"available": False,
                                  "note": ""}}


def _newer_version(conn, e: dict) -> dict | None:
    """Ижил багцын, туршилтын өгөгдлөөс хойших огноотой хамгийн сүүлийн бэлэн (архивлаагүй) файл."""
    return conn.execute(
        "SELECT v.id, v.version_no, v.date_max, v.file_name FROM raw.dataset_version v "
        "JOIN raw.dataset_version v0 ON v0.dataset_id = v.dataset_id WHERE v0.id=%s AND v.status='validated' "
        "AND v.archived_at IS NULL AND v.date_max > v0.date_max ORDER BY v.date_max DESC, v.id DESC LIMIT 1",
        (e["dataset_version_id"],)).fetchone()


@router.get("/forecasts/tracking")
def forecast_tracking(experiment_id: int, horizon: int = Query(12),
                      conn=Depends(get_conn, scope="function"), user=Depends(require("forecast_view"))):
    """FR-05, FR-15: таамаглал гаргаснаас хойш бодит өгөгдөл ирсэн саруудад таамаглалыг бодит утгатай харьцуулна.

    Бодит утга нь ижил багцад дараа нь оруулсан файлаас (шинэ хувилбар) ижил зорилтоор (борлуулалт / эрэлт)
    тооцогдоно. Бодит утга бүрдээгүй сард алдааг тэг гэж үзэхгүй — тэр сар харьцуулалтад орохгүй (NFR-13).
    Гараар зассан утга байвал «эцсийн» таамаглал нь засвар; системийн анхны утга тусад нь хадгалагдана."""
    if horizon not in HORIZONS:
        raise ApiError(422, "invalid_params", "Хугацаа буруу байна")
    e = _exp(conn, experiment_id)
    origin = last_complete_month(e["date_max"])
    base = {"experiment": {"id": e["id"], "name": e["name"], "target": e["target"],
                           "target_label": TARGET_LABELS[e["target"]], "dataset": e["dataset"]},
            "origin_date": origin.date(), "horizon": horizon, "period_label": PERIOD_LABELS[horizon]}
    if e["status"] != "test_done":
        return {**base, "available": False, "reason": "not_ready",
                "message": "Таамаглал бэлэн болоогүй байна."}
    nv = _newer_version(conn, e)
    if not nv:
        return {**base, "available": False, "reason": "no_new_data",
                "message": "Таамагласан саруудын бодит борлуулалт хараахан ороогүй байна. "
                           "Шинэ сарын файлаа ижил багцад оруулмагц энд харьцуулалт гарна."}
    sc, sp = scope_sql(user)
    rows = conn.execute(
        "SELECT ms.series_id, s.product_id, s.product_name, s.product_category, s.branch_id, s.unit, lr.run_id, lr.model, "
        "fv.h, fv.target_date, fv.y_hat FROM experiment.model_selection ms "
        "JOIN experiment.run sr ON sr.run_id = ms.run_id "
        "JOIN experiment.run lr ON lr.experiment_id = ms.experiment_id AND lr.phase='live' AND lr.model = sr.model "
        " AND lr.params = sr.params "
        "JOIN forecast.forecast_value fv ON fv.run_id = lr.run_id AND fv.series_id = ms.series_id AND fv.split='live' "
        "JOIN curated.series s ON s.id = ms.series_id "
        "WHERE ms.experiment_id=%s AND ms.horizon=%s AND fv.h <= %s" + sc + " ORDER BY ms.series_id, fv.h",
        [experiment_id, horizon, horizon, *sp]).fetchall()
    if not rows:
        return {**base, "available": False, "reason": "no_forecast", "message": "Таамаглал алга."}
    adj = {(a["run_id"], a["series_id"], a["target_date"]): a["adjusted_value"] for a in conn.execute(
        "SELECT DISTINCT ON (a.run_id, a.series_id, a.target_date) a.run_id, a.series_id, a.target_date, a.adjusted_value "
        "FROM governance.forecast_adjustment a JOIN experiment.run r ON r.run_id=a.run_id WHERE r.experiment_id=%s "
        "ORDER BY a.run_id, a.series_id, a.target_date, a.created_at DESC", (experiment_id,)).fetchall()}
    sids = sorted({r["series_id"] for r in rows})
    daily = load_daily(conn, nv["id"], sids)
    new_last = last_complete_month(nv["date_max"])
    actual: dict[int, pd.DataFrame] = {
        sid: build_monthly(d, e["target"], nv["date_max"]) for sid, d in daily.items()}

    items: dict[int, dict] = {}
    months: dict = {}
    for r in rows:
        m = pd.Timestamp(r["target_date"])
        it = items.setdefault(r["series_id"], {
            "series_id": r["series_id"], "product_id": r["product_id"], "product_name": r["product_name"],
            "product_category": r["product_category"], "branch_id": r["branch_id"], "unit": r["unit"],
            "model": r["model"], "months": []})
        if m > new_last:
            continue                                      # бодит өгөгдөл бүрдээгүй сар
        tab = actual.get(r["series_id"])
        y, why = None, "шинэ файлд энэ бараа алга"
        if tab is not None and m in tab.index:
            v = tab.loc[m, "y"]
            y, why = (None, tab.loc[m, "reason"]) if pd.isna(v) else (float(v), None)
        final = adj.get((r["run_id"], r["series_id"], r["target_date"]))
        it["months"].append({"month": r["target_date"], "h": r["h"], "forecast": float(r["y_hat"]),
                             "adjusted": None if final is None else float(final), "actual": y, "reason": why})

    def score(pairs: list[tuple[float, float]]) -> dict:
        """pairs: (таамаглал, бодит). WAPE = Σ|ŷ − y| / Σy; хазайлт = (Σŷ − Σy) / Σy."""
        if not pairs:
            return {"n": 0, "forecast": None, "actual": None, "abs_error": None, "wape": None, "bias": None}
        f = sum(p[0] for p in pairs)
        y = sum(p[1] for p in pairs)
        ae = sum(abs(p[0] - p[1]) for p in pairs)
        return {"n": len(pairs), "forecast": f, "actual": y, "abs_error": ae,
                "wape": ae / y if y > 0 else None, "bias": (f - y) / y if y > 0 else None}

    all_pairs, sys_pairs, out = [], [], []
    for it in items.values():
        pairs = [((x["adjusted"] if x["adjusted"] is not None else x["forecast"]), x["actual"])
                 for x in it["months"] if x["actual"] is not None]
        spairs = [(x["forecast"], x["actual"]) for x in it["months"] if x["actual"] is not None]
        it["score"] = score(pairs)
        it["system_score"] = score(spairs) if any(x["adjusted"] is not None for x in it["months"]) else None
        all_pairs += pairs
        sys_pairs += spairs
        for x in it["months"]:
            if x["actual"] is None:
                continue
            mm = months.setdefault(x["month"], {"month": x["month"], "forecast": 0.0, "actual": 0.0, "abs_error": 0.0, "n": 0})
            f = x["adjusted"] if x["adjusted"] is not None else x["forecast"]
            mm["forecast"] += f
            mm["actual"] += x["actual"]
            mm["abs_error"] += abs(f - x["actual"])
            mm["n"] += 1
        out.append(it)
    month_rows = []
    for k in sorted(months):
        mm = months[k]
        mm["wape"] = mm["abs_error"] / mm["actual"] if mm["actual"] > 0 else None
        month_rows.append(mm)
    n_months = months_between_incl(origin, min(new_last, add_months(origin, horizon)))
    out.sort(key=lambda it: -(it["score"]["abs_error"] or 0))
    units = sorted({it["unit"] for it in out})
    return {**base, "available": bool(all_pairs), "reason": None if all_pairs else "no_complete_month",
            "message": None if all_pairs else "Шинэ файлд таамагласан сараас бүтэн дууссан сар алга.",
            "actual_version": {"id": nv["id"], "version_no": nv["version_no"], "file_name": nv["file_name"],
                               "date_max": nv["date_max"], "last_complete_month": new_last.date()},
            "months_compared": n_months, "months_total": horizon,
            "unit": units[0] if len(units) == 1 else None,
            "overall": score(all_pairs),
            "system_overall": score(sys_pairs) if adj else None,
            "by_month": month_rows, "items": out}


def months_between_incl(origin: pd.Timestamp, last: pd.Timestamp) -> int:
    """origin-оос хойших, last хүртэлх (оруулаад) сарын тоо."""
    return max(0, (last.year - origin.year) * 12 + (last.month - origin.month))
