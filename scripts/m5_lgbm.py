"""M5-ийн ялагчдын арга барилаар (олон цуваанд нэг глобал LightGBM; Makridakis нар 2022) сарын таамаглал.
Харьцуулах зорилготой — системийн нэг хэсэг биш. Тестийн эхлэл бүрд (12) зөвхөн тухайн эхлэл хүртэлх
өгөгдлөөр дахин сургана (мэдээллийн алдагдалгүй). Шууд (direct) стратеги: h ∈ 1..12-ийг шинж болгоно.
Бүх 30 490 бараа×дэлгүүрт таамаглаад, дээд түвшинд доороос дээш (bottom-up) нийлүүлнэ.
Гаралт: <data>/lgbm_forecasts.parquet (id, origin, h, target, y_hat)
"""
import argparse
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--data", required=True)
ap.add_argument("--train-series", type=int, default=8000)
ap.add_argument("--train-origins", type=int, default=24, help="эхлэлийн өмнөх хэдэн эхлэлээр сургах")
ap.add_argument("--rounds", type=int, default=400)
ap.add_argument("--seed", type=int, default=20261117)
ap.add_argument("--origins", default="test", help="test | all")
ap.add_argument("--target", default="raw", choices=["raw", "ratio"],
                help="raw: ширхгээр (tweedie); ratio: сүүлийн 12 сарын дундажид харьцуулсан (түвшин, трендэд тэсвэртэй)")
a = ap.parse_args()
d = Path(a.data)
mon = pd.read_parquet(d / "m5_monthly.parquet")
meta = pd.read_parquet(d / "m5_meta.parquet")
months = pd.DatetimeIndex(sorted(mon.month.unique()))
ids = meta["id"].to_numpy()
Y = mon.pivot(index="id", columns="month", values="qty").loc[ids].to_numpy(float)       # NaN = зарагдаж эхлээгүй
P = mon.pivot(index="id", columns="month", values="price").loc[ids].to_numpy(float)
cats = {c: meta[c].astype("category").cat.codes.to_numpy() for c in ("dept_id", "cat_id", "store_id", "state_id")}   # item_id: өндөр кардиналтай, хэт тааруулдаг
N, T = Y.shape
FEATS = [f"lag{k}" for k in range(12)] + ["mean3", "mean6", "mean12", "std12", "zero12", "ly", "ly2", "age",
                                          "price", "price_rel", "tmonth", "h"] + list(cats) + ["log_scale"]


def feats(rows, t, h):
    """rows: цувааны индекс, t: эхлэлийн сарын индекс (мэдэгдэх сүүлийн сар), h: хүрээ. Зөвхөн ≤ t багана."""
    Yp = Y[rows, : t + 1]
    lags = np.stack([Yp[:, t - k] if t - k >= 0 else np.full(len(rows), np.nan) for k in range(12)], 1)
    w12 = Yp[:, max(0, t - 11): t + 1]
    with np.errstate(all="ignore"):
        f = {
            "mean3": np.nanmean(Yp[:, max(0, t - 2): t + 1], 1), "mean6": np.nanmean(Yp[:, max(0, t - 5): t + 1], 1),
            "mean12": np.nanmean(w12, 1), "std12": np.nanstd(w12, 1), "zero12": (w12 == 0).sum(1),
            "ly": Yp[:, t + h - 12] if 0 <= t + h - 12 <= t else np.full(len(rows), np.nan),
            "ly2": Yp[:, t + h - 24] if 0 <= t + h - 24 <= t else np.full(len(rows), np.nan),
            "age": (~np.isnan(Yp)).sum(1), "price": P[rows, t],
            "price_rel": P[rows, t] / np.nanmean(P[rows, max(0, t - 11): t + 1], 1),
            "tmonth": np.full(len(rows), (months[t].month - 1 + h) % 12 + 1),
            "h": np.full(len(rows), h),
        }
    sc = np.nan_to_num(f["mean12"], nan=0.0) + 1.0
    if a.target == "ratio":                     # түвшний шинжийг масштабаар хувааж, масштабыг тусад нь өгнө
        lags = lags / sc[:, None]
        for k in ("mean3", "mean6", "mean12", "std12", "ly", "ly2"):
            f[k] = f[k] / sc
    X = np.column_stack([lags] + [f[k] for k in FEATS[12:24]] + [cats[c][rows] for c in cats]
                        + [np.log1p(sc)]).astype(np.float32)
    return X, sc


test_start = months.get_loc(pd.Timestamp("2015-06-01"))
val_start = months.get_loc(pd.Timestamp("2014-06-01"))
t_list = range((val_start if a.origins == "all" else test_start) - 1, T - 1)
rng = np.random.default_rng(a.seed)
train_rows = np.sort(rng.choice(N, size=min(a.train_series, N), replace=False))
params = dict(objective="tweedie", tweedie_variance_power=1.2, learning_rate=0.05, num_leaves=63, min_data_in_leaf=100,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=a.seed,
              num_threads=0)
out = []
for t0 in t_list:
    tic = time.time()
    Xs, ys = [], []
    for t in range(max(12, t0 - a.train_origins), t0):        # сургалтын эхлэл t, зорилт t + h ≤ t0
        for h in range(1, 13):
            if t + h > t0:
                break
            y = Y[train_rows, t + h]
            ok = ~np.isnan(y)
            X_, sc_ = feats(train_rows[ok], t, h)
            Xs.append(X_); ys.append(y[ok] / sc_ if a.target == "ratio" else y[ok])
    X, yv = np.vstack(Xs), np.concatenate(ys)
    ds = lgb.Dataset(X, yv, feature_name=FEATS, categorical_feature=list(cats), free_raw_data=True)
    model = lgb.train(params, ds, num_boost_round=a.rounds)
    allr = np.arange(N)
    for h in range(1, 13):
        X_, sc_ = feats(allr, t0, h)
        yh = np.clip(model.predict(X_) * (sc_ if a.target == "ratio" else 1.0), 0, None)
        out.append(pd.DataFrame({"id": ids, "origin": months[t0], "h": h,
                                 "target": months[t0] + pd.DateOffset(months=h), "y_hat": yh}))
    print(f"эхлэл {months[t0].date()}: {len(yv):,} мөр, {time.time() - tic:.0f} с", flush=True)
res = pd.concat(out, ignore_index=True)
res.to_parquet(d / ("lgbm_forecasts.parquet" if a.target == "raw" else "lgbm_ratio_forecasts.parquet"), index=False)
imp = pd.Series(model.feature_importance("gain"), index=FEATS).sort_values(ascending=False)
imp.to_csv(d / f"lgbm_{a.target}_importance.csv")
print("дууслаа;", imp.head(8).round(0).to_dict())
