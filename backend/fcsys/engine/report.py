"""Туршилтын тайлан (FR-X2, FR-E1–E3, FR-M6, §4.8 дүрэм 8).

Хамрагдсан цуваа, бүтэлгүйтэл, хассан цуваа, ажиллах хугацаа, хувилбарыг үргэлж харуулна.
"Сонгосон" үр дүн нь цуваа, хүрээ бүрд validation-д сонгогдсон загварын ТЕСТИЙН алдаа.
"""
from __future__ import annotations

import io
import json

import numpy as np
import pandas as pd

from .evaluate import make_splits, origins_for
from .grid import TARGET_LABELS


def _label(model: str, params: dict) -> str:
    return model + (" " + json.dumps(params, ensure_ascii=False, sort_keys=True) if params else "")


def _dist(values: pd.Series) -> dict:
    v = values.dropna()
    if v.empty:
        return {"n": 0, "mean": None, "median": None, "p25": None, "p75": None}
    return {"n": int(len(v)), "mean": float(v.mean()), "median": float(v.median()),
            "p25": float(v.quantile(0.25)), "p75": float(v.quantile(0.75))}


def experiment_report(conn, eid: int) -> dict:
    e = conn.execute(
        "SELECT e.*, v.version_no, v.sha256, v.date_min, v.date_max, d.name AS dataset FROM experiment.experiment e "
        "JOIN raw.dataset_version v ON v.id=e.dataset_version_id JOIN raw.dataset d ON d.id=v.dataset_id "
        "WHERE e.id=%s", (eid,)).fetchone()
    proto = e["protocol"]
    sp = make_splits(pd.Timestamp(e["date_max"]), proto["val_days"], proto["test_days"], proto["train_min_days"])
    runs = pd.DataFrame(conn.execute(
        "SELECT r.run_id, r.phase, r.role, r.model, r.params, r.status, r.runtime_ms, r.code_version, r.lib_versions, "
        "r.input_checksum, r.seed, (SELECT count(*) FROM forecast.run_failure f WHERE f.run_id=r.run_id) AS n_failures, "
        "(SELECT count(DISTINCT series_id) FROM forecast.forecast_value fv WHERE fv.run_id=r.run_id) AS n_series "
        "FROM experiment.run r WHERE r.experiment_id=%s ORDER BY r.phase, r.run_id", (eid,)).fetchall())
    sample = conn.execute(
        "SELECT i.series_id, s.product_id, s.branch_id, i.included, i.exclude_reason FROM experiment.series_sample_item i "
        "JOIN experiment.series_sample ss ON ss.id=i.sample_id JOIN curated.series s ON s.id=i.series_id "
        "WHERE ss.experiment_id=%s ORDER BY s.product_id, s.branch_id", (eid,)).fetchall()
    rep: dict = {
        "experiment": {"id": e["id"], "name": e["name"], "status": e["status"], "target": e["target"],
                       "target_label": TARGET_LABELS[e["target"]], "protocol": proto,
                       "protocol_hash": e["protocol_hash"], "selection_hash": e["selection_hash"],
                       "protocol_locked_at": e["protocol_locked_at"], "locked_at": e["locked_at"]},
        "data": {"dataset": e["dataset"], "version_id": e["dataset_version_id"], "version_no": e["version_no"],
                 "sha256": e["sha256"], "date_min": e["date_min"], "date_max": e["date_max"]},
        "splits": {"train_start_min": sp.train_start.date(), "validation": [sp.val_start.date(), sp.val_end.date()],
                   "test": [sp.test_start.date(), sp.test_end.date()],
                   "validation_origins": [o.date() for o in origins_for(sp.val_start, sp.val_end, proto["step_days"], proto["H"])],
                   "test_origins": [o.date() for o in origins_for(sp.test_start, sp.test_end, proto["step_days"], proto["H"])]},
        "sample": {"included": sum(1 for s in sample if s["included"]),
                   "excluded": [s for s in sample if not s["included"]]},
        "runs": [], "validation": [], "selection": {}, "test": [], "by_class": [], "failures": [],
        "note": "Хэмжүүр бүр тухайн цувааны эхлэлүүдийн дундаж; тодорхойгүй утгыг хасаж, тоог n-д заав.",
    }
    if runs.empty:
        return rep
    runs["label"] = [_label(m, p) for m, p in zip(runs["model"], runs["params"])]
    rep["runs"] = runs.drop(columns=["params"]).to_dict(orient="records")

    em = pd.DataFrame(conn.execute(
        "SELECT em.run_id, em.series_id, em.split, em.horizon, em.metric, em.value, em.undefined_reason "
        "FROM forecast.error_metric em JOIN experiment.run r ON r.run_id=em.run_id "
        "WHERE r.experiment_id=%s AND em.origin_date IS NULL", (eid,)).fetchall(),
        columns=["run_id", "series_id", "split", "horizon", "metric", "value", "undefined_reason"])
    em["value"] = pd.to_numeric(em["value"], errors="coerce").astype(float)
    labels = runs.set_index("run_id")["label"].to_dict()
    metric = proto["selection_metric"]

    val = em[(em.split == "validation") & (em.metric == metric)]
    for (rid, hz), g in val.groupby(["run_id", "horizon"]):
        d = _dist(g["value"])
        rep["validation"].append({"run_id": int(rid), "model": labels[rid], "horizon": int(hz), "metric": metric,
                                  **d, "n_undefined": int(g["value"].isna().sum())})

    sel = pd.DataFrame(conn.execute(
        "SELECT ms.series_id, ms.horizon, ms.run_id, r.model, r.params, ms.rule FROM experiment.model_selection ms "
        "JOIN experiment.run r ON r.run_id=ms.run_id WHERE ms.experiment_id=%s", (eid,)).fetchall(),
        columns=["series_id", "horizon", "run_id", "model", "params", "rule"])
    if not sel.empty:
        sel["label"] = [_label(m, p) for m, p in zip(sel["model"], sel["params"])]
        for hz, g in sel.groupby("horizon"):
            rep["selection"][int(hz)] = {"counts": g["label"].value_counts().to_dict(),
                                         "rules": sorted(g["rule"].unique().tolist())[:10]}

    test_runs = runs[runs.phase == "test"]
    if not test_runs.empty and not sel.empty:
        key_to_test = {lbl: rid for rid, lbl in zip(test_runs["run_id"], test_runs["label"])}
        base_label = _label(proto["baseline"]["name"], proto["baseline"].get("params", {}))
        base_run = key_to_test.get(base_label)
        te = em[em.split == "test"]
        profiles = pd.DataFrame(conn.execute("SELECT series_id, class FROM curated.series_profile WHERE experiment_id=%s",
                                             (eid,)).fetchall(), columns=["series_id", "class"])
        for hz in proto["horizons"]:
            s = sel[sel.horizon == hz].copy()
            s["test_run"] = s["label"].map(key_to_test)
            chosen = te[te.horizon == hz].merge(s[["series_id", "test_run"]], left_on=["series_id", "run_id"],
                                                 right_on=["series_id", "test_run"])
            basel = te[(te.horizon == hz) & (te.run_id == base_run)]
            row = {"horizon": int(hz)}
            for mtr in ("MASE", "RMSSE", "WAPE", "MAE", "Bias", "SUM_AE"):
                row[f"selected_{mtr}"] = _dist(chosen[chosen.metric == mtr]["value"])
                row[f"baseline_{mtr}"] = _dist(basel[basel.metric == mtr]["value"])
            cm = chosen[chosen.metric == "MASE"].set_index("series_id")["value"]
            bm = basel[basel.metric == "MASE"].set_index("series_id")["value"]
            both = pd.concat([cm.rename("sel"), bm.rename("base")], axis=1).dropna()
            row["share_improved_vs_baseline"] = float((both["sel"] < both["base"]).mean()) if len(both) else None
            row["n_compared"] = int(len(both))
            cov = chosen[chosen.metric == "COVERAGE"]["value"]
            row["interval_coverage_80"] = _dist(cov)
            rep["test"].append(row)
            if not profiles.empty:                 # FR-E3: ADI/CV² бүлгээр
                byc = chosen[chosen.metric == "MASE"].merge(profiles, on="series_id")
                bb = basel[basel.metric == "MASE"].merge(profiles, on="series_id")
                for cls, g in byc.groupby("class"):
                    rep["by_class"].append({"horizon": int(hz), "class": cls, "selected_MASE": _dist(g["value"]),
                                            "baseline_MASE": _dist(bb[bb["class"] == cls]["value"])})
    fails = conn.execute(
        "SELECT f.run_id, r.phase, r.model, s.product_id, s.branch_id, f.origin_date, f.reason, f.fallback_model "
        "FROM forecast.run_failure f JOIN experiment.run r ON r.run_id=f.run_id JOIN curated.series s ON s.id=f.series_id "
        "WHERE r.experiment_id=%s ORDER BY f.run_id, s.product_id LIMIT 1000", (eid,)).fetchall()
    rep["failures"] = fails
    return rep


def report_xlsx(rep: dict) -> bytes:
    buf = io.BytesIO()
    exp = rep["experiment"]
    meta = [("Зорилт", exp["target_label"]), ("Туршилт", f"#{exp['id']} {exp['name']}"), ("Төлөв", exp["status"]),
            ("protocol_hash", exp["protocol_hash"]), ("selection_hash", exp["selection_hash"]),
            ("Өгөгдөл", f"{rep['data']['dataset']} v{rep['data']['version_no']}"),
            ("sha256", rep["data"]["sha256"]), ("Validation", " – ".join(map(str, rep["splits"]["validation"]))),
            ("Тест", " – ".join(map(str, rep["splits"]["test"]))),
            ("Хамрагдсан цуваа", rep["sample"]["included"]), ("Хасагдсан цуваа", len(rep["sample"]["excluded"])),
            ("Протокол", json.dumps(exp["protocol"], ensure_ascii=False))]
    flat_test = []
    for t in rep["test"]:
        r = {"horizon": t["horizon"], "share_improved_vs_baseline": t["share_improved_vs_baseline"],
             "n_compared": t["n_compared"]}
        for k, v in t.items():
            if isinstance(v, dict):
                r[f"{k}_mean"], r[f"{k}_median"], r[f"{k}_n"] = v["mean"], v["median"], v["n"]
        flat_test.append(r)
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame(meta, columns=["Талбар", "Утга"]).to_excel(xw, sheet_name="Хураангуй", index=False)
        runs = pd.DataFrame(rep["runs"])
        if "lib_versions" in runs:
            runs["lib_versions"] = runs["lib_versions"].map(lambda v: json.dumps(v, ensure_ascii=False))
        runs.to_excel(xw, sheet_name="Run", index=False)
        pd.DataFrame(rep["validation"]).to_excel(xw, sheet_name="Validation", index=False)
        pd.DataFrame(flat_test).to_excel(xw, sheet_name="Тест", index=False)
        pd.DataFrame([{**{k: v for k, v in r.items() if k not in ("selected_MASE", "baseline_MASE")},
                       "selected_mean": r["selected_MASE"]["mean"], "baseline_mean": r["baseline_MASE"]["mean"],
                       "n": r["selected_MASE"]["n"]} for r in rep["by_class"]]).to_excel(xw, sheet_name="Бүлгээр", index=False)
        pd.DataFrame(rep["failures"]).to_excel(xw, sheet_name="Бүтэлгүйтэл", index=False)
        pd.DataFrame(rep["sample"]["excluded"]).to_excel(xw, sheet_name="Хасагдсан цуваа", index=False)
    return buf.getvalue()
