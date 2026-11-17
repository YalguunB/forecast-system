"""M5 дээр системийн загваруудыг системийн протоколоор (сургалт ≥ 24, validation 12, тест 12 сар,
эхлэл сар бүр, H = 12) ажиллуулж, бүх таамаглалыг хадгална. Системийн кодыг (fcsys.engine.models) шууд ашиглана.

Түвшин:  store (10 дэлгүүр) · dept_store (70) · item_store (санамсаргүй --n бараа×дэлгүүр, ангиллаар давхарласан)
Гаралт:  <out>/stat_forecasts.parquet (level, sid, model, origin, h, target, y_hat), <out>/series.parquet
Хэрэглээ: python scripts/m5_run.py --data /tmp/m5/out --n 300 --jobs 2
"""
import argparse
import os
import sys
import time
import warnings
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fcsys.engine.models import FitContext, make_model, run_series  # noqa: E402

MODELS = {   # системийн DEFAULT_PROTOCOL-ийн загварууд (combo-г бүрэлдэхүүнээс нь дундажлана — ижил тодорхойлолт)
    "ma": ("ma", {"window": 3}), "naive": ("naive", {}), "snaive": ("snaive", {"m": 12}),
    "ets": ("ets", {"seasonal": "add"}), "ets_damped": ("ets", {"seasonal": "add", "trend": "add", "damped": True}),
    "sarima": ("sarima", {"order": [1, 1, 1], "seasonal_order": [0, 1, 1]}),
    "croston": ("croston", {"alpha": 0.1}), "sba": ("sba", {"alpha": 0.1}),
}
VAL_START, TEST_START, LAST = pd.Timestamp("2014-06-01"), pd.Timestamp("2015-06-01"), pd.Timestamp("2016-05-01")
TRAIN_START = pd.Timestamp("2012-06-01")       # validation-ээс 24 сарын өмнө
ORIGINS = pd.date_range(VAL_START - pd.DateOffset(months=1), LAST - pd.DateOffset(months=1), freq="MS")


def one(args):
    level, sid, y = args
    warnings.simplefilter("ignore")
    fb = make_model("ma", {"window": 3})
    out, fails = [], 0
    for o in ORIGINS:
        ctx = FitContext(series_id=0, origin=o, target="sales", horizon=12, seed=1)
        preds = {}
        for name, (m, p) in MODELS.items():
            f, err = run_series(make_model(m, p), y, ctx, fb)
            fails += err is not None
            preds[name] = f["y_hat"].to_numpy()
        preds["combo"] = np.mean([preds["ets"], preds["ets_damped"], preds["sarima"]], axis=0)
        tgt = pd.date_range(o + pd.DateOffset(months=1), periods=12, freq="MS")
        for name, v in preds.items():
            out.append(pd.DataFrame({"level": level, "sid": sid, "model": name, "origin": o,
                                     "h": np.arange(1, 13), "target": tgt, "y_hat": v}))
    return pd.concat(out), fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    ap.add_argument("--seed", type=int, default=20261117)
    a = ap.parse_args()
    d = Path(a.data)
    mon = pd.read_parquet(d / "m5_monthly.parquet")
    meta = pd.read_parquet(d / "m5_meta.parquet")
    mon = mon.merge(meta, on="id")
    q0 = mon.assign(qty=mon.qty.fillna(0))
    series = {}
    for s, g in q0.groupby("store_id"):
        series[("store", s)] = g.groupby("month").qty.sum()
    for (s, dp), g in q0.groupby(["store_id", "dept_id"]):
        series[("dept_store", f"{dp}_{s}")] = g.groupby("month").qty.sum()
    # бараа×дэлгүүр: сургалтын эхнээс (2012-06) өмнө зарагдаж эхэлсэн цуваа (системийн min_length дүрэм)
    alive = mon[mon.month == TRAIN_START].dropna(subset=["qty"])[["id", "cat_id"]]
    rng = np.random.default_rng(a.seed)
    pick = []
    for cat, g in alive.groupby("cat_id"):
        k = round(a.n * len(g) / len(alive))
        pick += list(rng.choice(g["id"].to_numpy(), size=k, replace=False))
    wide = mon[mon.id.isin(pick)].pivot(index="month", columns="id", values="qty")
    for i in pick:
        series[("item_store", i)] = wide[i]
    rows = [{"level": l, "sid": s, "n_months": int(y.notna().sum()), "total": float(y.sum()),
             "zero_share": float((y.loc[TRAIN_START:] == 0).mean())} for (l, s), y in series.items()]
    pd.DataFrame(rows).to_parquet(d / "series.parquet", index=False)
    jobs = [(l, s, y.asfreq("MS")) for (l, s), y in series.items()]
    print(f"{len(jobs)} цуваа, {len(ORIGINS)} эхлэл, {len(MODELS) + 1} загвар", flush=True)
    t0, res, fails = time.time(), [], 0
    with Pool(a.jobs) as pool:
        for i, (df, f) in enumerate(pool.imap_unordered(one, jobs, chunksize=2), 1):
            res.append(df); fails += f
            if i % 20 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)}  {time.time() - t0:.0f} с, fallback {fails}", flush=True)
    pd.concat(res).to_parquet(d / "stat_forecasts.parquet", index=False)
    print("дууслаа", d / "stat_forecasts.parquet")


if __name__ == "__main__":
    main()
