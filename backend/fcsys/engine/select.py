"""select — загварыг validation-д сонгох (FR-M4, §4.4 «Сонголтын дүрэм»).

Дүрэм: сонгосон түвшинд (цуваа / ADI-CV² бүлэг / нийт) validation-ийн хэмжүүрийн дундаж
хамгийн бага хувилбарыг сонгоно; суурь загвараас (seasonal naive) сайн биш бол суурийг
сонгоно (§2.3.1). Тестийн алдааг энэ модуль хэзээ ч уншихгүй.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def select_models(metrics: pd.DataFrame, profiles: pd.DataFrame, runs: pd.DataFrame,
                  baseline_run_id: int, level: str, metric: str = "MASE") -> pd.DataFrame:
    """metrics: validation-ийн эхлэл тус бүрийн мөр (run_id, series_id, horizon, metric, value).
    profiles: series_id, class. Буцаах: series_id, horizon, run_id, rule, score."""
    m = metrics[(metrics["metric"] == metric) & metrics["origin_date"].notna()].copy()
    m = m.merge(profiles[["series_id", "class"]], on="series_id", how="left")
    if level == "series":
        m["grp"] = m["series_id"].astype(str)
    elif level == "group":
        m["grp"] = m["class"].fillna("unknown")
    else:
        m["grp"] = "all"
    names = runs.set_index("run_id")["label"].to_dict()
    out = []
    series_grp = m[["series_id", "grp"]].drop_duplicates()
    for (grp, hz), g in m.groupby(["grp", "horizon"]):
        score = g.groupby("run_id")["value"].mean()        # тодорхойгүй (NaN) утгыг алгасна
        coverage = g.groupby("run_id")["value"].apply(lambda s: s.notna().mean())
        score = score[coverage >= 0.5].dropna()            # хагасаас олонд тодорхойгүй бол оролцохгүй
        base = score.get(baseline_run_id, np.nan)
        if score.empty:
            chosen, rule = baseline_run_id, f"{metric} тодорхойгүй → суурь загвар"
            val = None
        else:
            best = int(score.idxmin())
            if np.isnan(base) or score[best] < base:
                chosen = best
                rule = f"min mean {metric} ({level}:{grp}) = {score[best]:.4f}"
                if not np.isnan(base):
                    rule += f" < суурь {base:.4f}"
            else:
                chosen = baseline_run_id
                rule = (f"{names.get(best, best)} ({score[best]:.4f}) суурь загвараас "
                        f"({base:.4f}) сайн биш → суурь загвар")
            val = float(score.get(chosen, np.nan)) if chosen in score else None
        for sid in series_grp.loc[series_grp.grp == grp, "series_id"]:
            out.append({"series_id": int(sid), "horizon": int(hz), "run_id": int(chosen),
                        "rule": rule, "score": val})
    return pd.DataFrame(out)
