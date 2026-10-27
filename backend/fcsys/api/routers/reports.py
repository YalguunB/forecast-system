"""Тайлангийн самбар — нэг туршилтын сарын нэгтгэсэн үзүүлэлт, график (Power BI маягийн дэлгэц).

Нэг хүсэлтээр бүх графикийн өгөгдлийг буцаана; цуваа бүрийн сарын массивыг илгээдэг тул frontend нь
бүтээгдэхүүний нэр, ангилал, салбараар шүүх, нэгтгэхэд дахин хүсэлт илгээхгүй.
Хугацааны нийлбэр (сар, улирал, жил) = сарын цэгэн таамаглалын нийлбэр (тэгшитгэл 2.2).
"""
from __future__ import annotations

import datetime as dt
import io

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from ...db import audit
from ...engine.grid import TARGET_LABELS
from ...engine.monthly import HORIZONS, PERIOD_LABELS, add_months, build_monthly, last_complete_month
from ...engine.store import load_daily
from ..core import ApiError, get_conn, not_found, require, require_monthly, scope_sql

router = APIRouter(tags=["reports"])

NO_CATEGORY = "Ангилалгүй"


def _f(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 4)


def _sum_or_none(vals):
    v = [x for x in vals if x is not None]
    return float(sum(v)) if len(v) == len(vals) and v else None


def build_dashboard(conn, user, experiment_id: int, horizon: int, history_months: int) -> dict:
    if horizon not in HORIZONS:
        raise ApiError(422, "invalid_params", "horizon ∈ {1, 3, 12} (сар, улирал, жил)")
    e = conn.execute("SELECT e.*, v.date_max, v.version_no, d.name AS dataset FROM experiment.experiment e "
                     "JOIN raw.dataset_version v ON v.id=e.dataset_version_id JOIN raw.dataset d ON d.id=v.dataset_id "
                     "WHERE e.id=%s", (experiment_id,)).fetchone()
    if not e:
        raise not_found("Туршилт", experiment_id)
    require_monthly(e)
    if e["status"] != "test_done":
        raise ApiError(409, "not_ready", "Тайлан тест дууссан туршилтад л гарна")

    series = conn.execute(
        "SELECT s.id, s.product_id, s.product_name, coalesce(nullif(s.product_category, ''), %s) AS category, "
        "s.branch_id, s.unit, coalesce(p.class, 'unknown') AS class "
        "FROM experiment.series_sample_item i JOIN experiment.series_sample ss ON ss.id=i.sample_id "
        "JOIN curated.series s ON s.id=i.series_id "
        "LEFT JOIN curated.series_profile p ON p.experiment_id=ss.experiment_id AND p.series_id=s.id "
        "WHERE ss.experiment_id=%s AND i.included" + scope_sql(user)[0] +
        " ORDER BY coalesce(s.product_name, s.product_id), s.branch_id",
        [NO_CATEGORY, experiment_id, *scope_sql(user)[1]]).fetchall()
    sids = [s["id"] for s in series]
    daily = load_daily(conn, e["dataset_version_id"], sids)
    last = last_complete_month(e["date_max"])
    hist_months = pd.date_range(add_months(last, -(history_months - 1)), last, freq="MS")
    fc_months = pd.date_range(add_months(last, 1), periods=horizon, freq="MS")
    ly_months = fc_months - pd.DateOffset(months=12)

    # Ирээдүйн таамаглал: тухайн хүрээнд сонгогдсон загварын live run, h ≤ horizon
    fc = pd.DataFrame(conn.execute(
        "SELECT fv.series_id, fv.target_date, fv.y_hat, r.model, r.params FROM forecast.forecast_value fv "
        "JOIN experiment.run r ON r.run_id=fv.run_id "
        "JOIN experiment.model_selection ms ON ms.experiment_id=r.experiment_id AND ms.series_id=fv.series_id "
        "  AND ms.horizon=%s "
        "JOIN experiment.run vr ON vr.run_id=ms.run_id AND vr.model=r.model AND vr.params=r.params "
        "WHERE r.experiment_id=%s AND fv.split='live' AND fv.h <= %s",
        (horizon, experiment_id, horizon)).fetchall(), columns=["series_id", "target_date", "y_hat", "model", "params"])
    if not fc.empty:
        fc["target_date"] = pd.to_datetime(fc["target_date"])

    states: dict[str, int] = {}
    per_series = []
    total_all = None
    for s in series:
        d = daily.get(s["id"])
        if d is None:
            continue
        t = build_monthly(d, e["target"], e["date_max"])
        y = t["y"].astype(float)
        total_all = y.fillna(0) if total_all is None else total_all.add(y.fillna(0), fill_value=0)
        for k, v in d["day_state"].value_counts().items():
            states[k] = states.get(k, 0) + int(v)
        f = fc[fc.series_id == s["id"]]
        fser = f.set_index("target_date")["y_hat"].reindex(fc_months) if len(f) else pd.Series(np.nan, index=fc_months)
        h = y.reindex(hist_months)
        ly = [_f(v) for v in y.reindex(ly_months).values]
        fvals = [_f(v) for v in fser.values]
        total = _sum_or_none(fvals)
        last_year = _sum_or_none(ly)
        per_series.append({**s, "model": f["model"].iloc[0] if len(f) else None,
                           "history": [_f(v) for v in h.values], "forecast": fvals,
                           "total_forecast": _f(total), "last_year": _f(last_year),
                           "growth": _f(total / last_year - 1) if total is not None and last_year else None})

    # Улирлын хэв шинж: он × сар, сарын нийт борлуулалт
    season = None
    month_rows = []
    if total_all is not None and len(total_all):
        tt = total_all.to_frame("v")
        tt["year"], tt["m"] = tt.index.year, tt.index.month
        piv = tt.pivot_table(index="year", columns="m", values="v", aggfunc="sum").reindex(columns=range(1, 13))
        season = {"rows": [int(r) for r in piv.index], "cols": list(range(1, 13)),
                  "z": [[_f(v) for v in row] for row in piv.values]}
        month_rows = [{"month": m.strftime("%Y-%m"), "total": _f(v)} for m, v in total_all.iloc[-36:].items()]

    # Validation: загвар × хүрээ, WAPE-ийн цувааны дундаж
    val = conn.execute(
        "SELECT r.model, r.params, r.role, em.horizon, avg(em.value) AS wape, count(em.value) AS n "
        "FROM forecast.error_metric em JOIN experiment.run r ON r.run_id=em.run_id "
        "WHERE r.experiment_id=%s AND em.split='validation' AND em.metric='WAPE' AND em.origin_date IS NULL "
        "GROUP BY 1,2,3,4 ORDER BY 1,4", (experiment_id,)).fetchall()

    # Тест: цуваа бүрийн сонгосон ба суурь загварын алдаа (сонгосон хүрээнд)
    test = conn.execute("""
        WITH sel AS (
          SELECT ms.series_id, tr.run_id FROM experiment.model_selection ms
            JOIN experiment.run vr ON vr.run_id = ms.run_id
            JOIN experiment.run tr ON tr.experiment_id = ms.experiment_id AND tr.phase = 'test'
                                  AND tr.model = vr.model AND tr.params = vr.params
           WHERE ms.experiment_id = %(e)s AND ms.horizon = %(h)s),
        base AS (SELECT run_id FROM experiment.run WHERE experiment_id = %(e)s AND phase = 'test' AND role = 'baseline')
        SELECT em.series_id, em.metric,
               max(em.value) FILTER (WHERE em.run_id = sel.run_id) AS selected,
               max(em.value) FILTER (WHERE em.run_id IN (SELECT run_id FROM base)) AS baseline
          FROM forecast.error_metric em JOIN sel ON sel.series_id = em.series_id
         WHERE em.split = 'test' AND em.horizon = %(h)s AND em.origin_date IS NULL
           AND em.metric IN ('WAPE', 'SUM_APE', 'COVERAGE', 'Bias', 'MAE')
           AND (em.run_id = sel.run_id OR em.run_id IN (SELECT run_id FROM base))
         GROUP BY 1, 2""", {"e": experiment_id, "h": horizon}).fetchall()
    tdf = pd.DataFrame(test, columns=["series_id", "metric", "selected", "baseline"])
    tdf = tdf[tdf.series_id.isin(sids)]          # менежер: зөвхөн өөрийн салбар
    for c in ("selected", "baseline"):
        tdf[c] = pd.to_numeric(tdf[c], errors="coerce").astype(float)

    def med(metric, col):
        v = tdf.loc[tdf.metric == metric, col].dropna()
        return _f(v.median()) if len(v) else None

    wape = tdf[tdf.metric == "WAPE"].dropna(subset=["selected", "baseline"])
    kpi = {"wape_selected": med("WAPE", "selected"), "wape_baseline": med("WAPE", "baseline"),
           "period_error_selected": med("SUM_APE", "selected"), "period_error_baseline": med("SUM_APE", "baseline"),
           "share_improved": _f((wape.selected < wape.baseline).mean()) if len(wape) else None,
           "coverage": med("COVERAGE", "selected"), "n_series": len(per_series)}
    per_test = {}
    for r in tdf.itertuples():
        per_test.setdefault(int(r.series_id), {})[r.metric] = {"selected": _f(r.selected), "baseline": _f(r.baseline)}
    for s in per_series:
        s["test"] = per_test.get(s["id"], {})

    unit = series[0]["unit"] if series else ""
    return {
        "grain": "month",
        "experiment": {"id": e["id"], "name": e["name"], "dataset": e["dataset"], "version_no": e["version_no"],
                       "target": e["target"], "target_label": TARGET_LABELS[e["target"]], "unit": unit,
                       "last_month": last.date(), "horizon": horizon, "period_label": PERIOD_LABELS[horizon]},
        "history_months": [m.date() for m in hist_months], "forecast_months": [m.date() for m in fc_months],
        "series": per_series, "kpi": kpi, "monthly": month_rows, "season": season,
        "validation": [{"model": r["model"], "params": r["params"], "role": r["role"], "horizon": r["horizon"],
                        "wape": _f(r["wape"]), "n": r["n"]} for r in val],
        "states": states,
        "note": "Хугацааны нийлбэр нь сарын цэгэн таамаглалын нийлбэр; интервалын хязгаарыг нэмээгүй. "
                "Өмнөх оны харьцуулалт нь ижил саруудын бодит борлуулалт (бүтэн сар байвал).",
    }


@router.get("/reports/dashboard")
def dashboard(experiment_id: int, horizon: int = Query(12), history_months: int = Query(24, ge=6, le=120),
              conn=Depends(get_conn), user=Depends(require("forecast_view"))):
    return build_dashboard(conn, user, experiment_id, horizon, history_months)


def _group_table(series: list[dict], key: str, label: str, months: list) -> pd.DataFrame:
    rows: dict = {}
    for s in series:
        k = s[key] if key != "product" else (s["product_name"] or s["product_id"])
        r = rows.setdefault(k, {label: k, "n": 0, "forecast": 0.0, "fc_ok": True, "last_year": 0.0, "ly_ok": True,
                                "months": [0.0] * len(months), "wape": []})
        r["n"] += 1
        if s["total_forecast"] is None:
            r["fc_ok"] = False
        else:
            r["forecast"] += s["total_forecast"]
        if s["last_year"] is None:
            r["ly_ok"] = False
        else:
            r["last_year"] += s["last_year"]
        for i, v in enumerate(s["forecast"]):
            r["months"][i] += v or 0.0
        w = s.get("test", {}).get("WAPE", {}).get("selected")
        if w is not None:
            r["wape"].append(w)
    out = []
    for r in rows.values():
        fc = r["forecast"] if r["fc_ok"] else None
        ly = r["last_year"] if r["ly_ok"] else None
        rec = {label: r[label], "Цувааны тоо": r["n"], "Таамаглал (нийт)": fc, "Өмнөх оны ижил үе": ly,
               "Өөрчлөлт %": round((fc / ly - 1) * 100, 1) if fc is not None and ly else None,
               "Тестийн WAPE (медиан) %": round(float(np.median(r["wape"])) * 100, 1) if r["wape"] else None}
        for m, v in zip(months, r["months"]):
            rec[pd.Timestamp(m).strftime("%Y-%m")] = round(v, 2)
        out.append(rec)
    df = pd.DataFrame(out)
    return df.sort_values("Таамаглал (нийт)", ascending=False, na_position="last") if not df.empty else df


@router.get("/reports/summary.xlsx")
def summary_xlsx(experiment_id: int, horizon: int = Query(12), conn=Depends(get_conn),
                 user=Depends(require("export"))):
    """Ангиллаар, бүтээгдэхүүний нэрээр, салбараар нэгтгэсэн тайлан (Excel)."""
    rep = build_dashboard(conn, user, experiment_id, horizon, 24)
    ex = rep["experiment"]
    months = rep["forecast_months"]
    meta = pd.DataFrame([("Тайлан", f"{ex['target_label']} — {ex['period_label']} ({horizon} сар)"),
                         ("Туршилт", f"#{ex['id']} {ex['name']}"), ("Өгөгдөл", f"{ex['dataset']} v{ex['version_no']}"),
                         ("Сүүлийн бүтэн сар", str(ex["last_month"])),
                         ("Таамагласан сар", f"{months[0]} – {months[-1]}"), ("Нэгж", ex["unit"]),
                         ("Хэрэглэгч", f"{user['username']} {dt.datetime.now():%Y-%m-%d %H:%M}"),
                         ("Тайлбар", rep["note"])], columns=["Талбар", "Утга"])
    detail = pd.DataFrame([{"Бүтээгдэхүүн": s["product_name"] or s["product_id"], "Код": s["product_id"],
                            "Ангилал": s["category"], "Салбар": s["branch_id"], "Нэгж": s["unit"],
                            "Арга": s["model"], "Таамаглал (нийт)": s["total_forecast"],
                            "Өмнөх оны ижил үе": s["last_year"],
                            "Өөрчлөлт %": round(s["growth"] * 100, 1) if s["growth"] is not None else None,
                            **{pd.Timestamp(m).strftime("%Y-%m"): v for m, v in zip(months, s["forecast"])}}
                           for s in rep["series"]])
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        meta.to_excel(xw, sheet_name="Мэдээлэл", index=False)
        _group_table(rep["series"], "category", "Ангилал", months).to_excel(xw, sheet_name="Ангиллаар", index=False)
        _group_table(rep["series"], "product", "Бүтээгдэхүүн", months).to_excel(xw, sheet_name="Бүтээгдэхүүнээр", index=False)
        _group_table(rep["series"], "branch_id", "Салбар", months).to_excel(xw, sheet_name="Салбараар", index=False)
        detail.to_excel(xw, sheet_name="Цуваа бүрээр", index=False)
    audit(conn, user["id"], "export_summary", "experiment", experiment_id, {"horizon": horizon})
    return StreamingResponse(io.BytesIO(out.getvalue()),
                             media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition":
                                      f'attachment; filename="report_exp{experiment_id}_{horizon}m.xlsx"'})
