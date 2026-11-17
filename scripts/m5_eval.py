"""M5 туршилтын үнэлгээ: системийн загварууд (+ системийн сонголтын дүрэм) ба LightGBM-ийг тестийн 12 сард харьцуулна.
Хэмжүүр системийнхтэй ижил (fcsys.engine.evaluate): хүрээ k ∈ {1,3,12}, эхлэл o-д o+1..o+k сарууд.
  WAPE  = Σ|ŷ−y| / Σy (бүх цуваа, эхлэлээр нэгтгэсэн)
  PAPE  = Σ|Σŷ−Σy| / ΣΣy — хугацааны нийт дүнгийн алдаа (сар/улирал/жилийн нийт захиалгад хамгийн чухал)
  MASE  = цуваа бүрийн MASE-ийн медиан (m = 12)
Сонголт: validation-ийн (series, origin) WAPE-ийн дундаж хамгийн бага загвар; суурь (ma) -аас сайн биш бол суурь.
Гаралт: <data>/m5_results.csv, m5_selection.csv, m5_lgbm_by_cat.csv
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--data", required=True)
a = ap.parse_args()
d = Path(a.data)
VAL = (pd.Timestamp("2014-06-01"), pd.Timestamp("2015-05-01"))
TEST = (pd.Timestamp("2015-06-01"), pd.Timestamp("2016-05-01"))
TRAIN_START = pd.Timestamp("2012-06-01")
K = (1, 3, 12)
LABEL = {"ma": "Гулсах дундаж (3 сар), суурь", "naive": "Naive", "snaive": "Улирлын naive", "ets": "ETS (улиралтай)",
         "ets_damped": "ETS (сааруулсан тренд)", "sarima": "SARIMA", "combo": "Хосолсон (ETS+ETS+SARIMA)",
         "croston": "Croston", "sba": "SBA", "selected": "Системийн сонголт", "lgbm": "LightGBM (глобал, ширхгээр)", "lgbm_ratio": "LightGBM (глобал, харьцангуй)"}

mon = pd.read_parquet(d / "m5_monthly.parquet").merge(pd.read_parquet(d / "m5_meta.parquet"), on="id")
mon["qty0"] = mon.qty.fillna(0)
ser = pd.read_parquet(d / "series.parquet")
st = pd.read_parquet(d / "stat_forecasts.parquet")

# Бодит утга түвшин бүрд
act = [mon.groupby(["store_id", "month"]).qty0.sum().rename("y").reset_index().rename(columns={"store_id": "sid"}).assign(level="store")]
g = mon.groupby(["dept_id", "store_id", "month"]).qty0.sum().rename("y").reset_index()
g["sid"] = g.dept_id + "_" + g.store_id
act.append(g[["sid", "month", "y"]].assign(level="dept_store"))
items = ser.loc[ser.level == "item_store", "sid"]
act.append(mon[mon.id.isin(items)][["id", "month", "qty"]].rename(columns={"id": "sid", "qty": "y"}).assign(level="item_store"))
act = pd.concat(act, ignore_index=True)

# LightGBM: бараа түвшний таамаглалыг дээш нийлүүлнэ (bottom-up). raw ба ratio хувилбар.
meta = pd.read_parquet(d / "m5_meta.parquet")


def bottom_up(path, name):
    lg = pd.read_parquet(path).merge(meta, on="id")
    out = [lg[lg.id.isin(items)].rename(columns={"id": "sid"})[["sid", "origin", "h", "target", "y_hat"]].assign(level="item_store")]
    x = lg.groupby(["store_id", "origin", "h", "target"]).y_hat.sum().reset_index().rename(columns={"store_id": "sid"})
    out.append(x.assign(level="store"))
    x = lg.groupby(["dept_id", "store_id", "origin", "h", "target"]).y_hat.sum().reset_index()
    x["sid"] = x.dept_id + "_" + x.store_id
    out.append(x[["sid", "origin", "h", "target", "y_hat"]].assign(level="dept_store"))
    return pd.concat(out).assign(model=name)


lgs = [bottom_up(d / f, n) for f, n in (("lgbm_forecasts.parquet", "lgbm"), ("lgbm_ratio_forecasts.parquet", "lgbm_ratio"))
       if (d / f).exists()]
fc = pd.concat([st, *lgs], ignore_index=True)
fc = fc.merge(act.rename(columns={"month": "target"}), on=["level", "sid", "target"], how="left")

# MASE масштаб: сургалтын хэсгийн (тест/validation эхлэхээс өмнөх) 12-сарын зөрүүний дундаж
def scale(section_start):
    h = act[act.month < section_start].sort_values("month")
    h["d"] = h.groupby(["level", "sid"]).y.diff(12).abs()
    return h.groupby(["level", "sid"]).d.mean().rename("q").reset_index()


def per_origin(df, section):
    s0, s1 = section
    df = df[(df.origin >= s0 - pd.DateOffset(months=1)) & (df.target <= s1)]
    rows = []
    for k in K:
        x = df[df.h <= k].copy()
        # o + k ≤ хэсгийн төгсгөл
        x = x[x.origin + pd.DateOffset(months=k) <= s1]
        x = x.dropna(subset=["y"])
        x["ae"] = (x.y_hat - x.y).abs()
        agg = x.groupby(["level", "model", "sid", "origin"]).agg(ae=("ae", "sum"), sy=("y", "sum"), sf=("y_hat", "sum"),
                                                                 n=("y", "size")).reset_index()
        agg["k"] = k
        rows.append(agg)
    r = pd.concat(rows)
    r["wape"] = r.ae / r.sy.replace(0, np.nan)
    r["pae"] = (r.sf - r.sy).abs()
    return r.merge(scale(s0), on=["level", "sid"], how="left")


val, test = per_origin(fc, VAL), per_origin(fc, TEST)

# Системийн сонголт (global, WAPE, суурь = ma). LightGBM сонголтод оролцохгүй.
sel = []
for (lvl, k), g in val[~val.model.str.startswith("lgbm")].groupby(["level", "k"]):
    sc = g.groupby("model").wape.mean()
    best = sc.idxmin()
    chosen = best if sc[best] < sc["ma"] else "ma"
    sel.append({"level": lvl, "k": k, "selected": chosen, "val_wape": round(sc[chosen], 4),
                "val_scores": "; ".join(f"{m}={v:.3f}" for m, v in sc.sort_values().items())})
sel = pd.DataFrame(sel)
sel.to_csv(d / "m5_selection.csv", index=False)
s_map = {(r.level, r.k): r.selected for r in sel.itertuples()}
picked = pd.concat([test[(test.level == l) & (test.k == k) & (test.model == m)].assign(model="selected")
                    for (l, k), m in s_map.items()])
test = pd.concat([test, picked])

res = test.groupby(["level", "k", "model"]).apply(lambda g: pd.Series({
    "WAPE": g.ae.sum() / g.sy.sum(), "PAPE": g.pae.sum() / g.sy.sum(),
    "MASE": (g.ae / g.n / g.q).median(), "n_series": g.sid.nunique()}), include_groups=False).reset_index()
res["label"] = res.model.map(LABEL)
res.to_csv(d / "m5_results.csv", index=False)
pd.set_option("display.width", 200)
for lvl in ("store", "dept_store", "item_store"):
    t = res[res.level == lvl].pivot(index="model", columns="k", values=["WAPE", "PAPE"]).round(3)
    print(f"\n== {lvl} (n={int(res[res.level == lvl].n_series.max())})  сонголт:",
          {k: s_map[(lvl, k)] for k in K})
    print(t.sort_values(("WAPE", 1)))

# Ангиллаар (бараа түвшин, k=1): системийн сонголт ба LightGBM
it = test[(test.level == "item_store") & (test.k == 1) & test.model.isin(["selected", "lgbm", "lgbm_ratio", "ma", "ets", "sba"])]
it = it.merge(mon[["id", "cat_id"]].drop_duplicates().rename(columns={"id": "sid"}), on="sid")
bc = it.groupby(["cat_id", "model"]).apply(lambda g: g.ae.sum() / g.sy.sum(), include_groups=False).unstack().round(3)
bc.to_csv(d / "m5_by_cat.csv")
print("\nАнгиллаар (бараа×дэлгүүр, сар, WAPE):\n", bc)
