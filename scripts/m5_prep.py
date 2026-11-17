"""M5 (Walmart, Makridakis нар 2022) өгөгдлийг сарын түвшинд нэгтгэнэ.

Оролт: Kaggle/Nixtla-ийн m5.zip задалсан хавтас (sales_train_evaluation.csv, sales_test_evaluation.csv,
calendar.csv, sell_prices.csv). Гаралт (--out):
  m5_monthly.parquet  — бараа×дэлгүүр×сар: qty, price, days (тухайн сард байсан өдөр), zero_days
  m5_meta.parquet     — бараа×дэлгүүрийн item_id, dept_id, cat_id, store_id, state_id
  upload/<store>/transactions.csv — системд оруулах өдрийн гүйлгээ (--upload-store, --upload-n)
Бүтэн сар: 2011-02 … 2016-05 (64 сар). 2011-01-29..31 ба 2016-06-01..19 хагас сар тул хасна.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--src", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--upload-store", default="CA_1")
ap.add_argument("--upload-n", type=int, default=100, help="системд оруулах барааны тоо (борлуулалтаар эрэмбэлж, давхаргаар)")
a = ap.parse_args()
src, out = Path(a.src), Path(a.out)
out.mkdir(parents=True, exist_ok=True)

cal = pd.read_csv(src / "calendar.csv", parse_dates=["date"])
cal["d"] = "d_" + (cal.index + 1).astype(str)     # Nixtla-ийн хувилбарт d багана алга: мөрийн дараалал
tr = pd.read_csv(src / "sales_train_evaluation.csv")
te = pd.read_csv(src / "sales_test_evaluation.csv")     # d_1942..1969 (2016-05-23 … 06-19), id баганагүй
ids = ["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"]
for d in (tr, te):
    d.insert(0, "id", d["item_id"] + "_" + d["store_id"] + "_evaluation")
te = te.set_index("id").loc[tr["id"]].reset_index()
dcols = [c for c in tr.columns if c.startswith("d_")] + [c for c in te.columns if c.startswith("d_")]
Y = np.hstack([tr[[c for c in tr.columns if c.startswith("d_")]].to_numpy(np.int32),
               te[[c for c in te.columns if c.startswith("d_")]].to_numpy(np.int32)])
dates = cal.set_index("d").loc[dcols, "date"].to_numpy()
meta = tr[ids].copy()
print("цуваа", Y.shape, "өдөр", pd.Timestamp(dates[0]).date(), "…", pd.Timestamp(dates[-1]).date())

# Бараа зарагдаж эхлэхээс өмнөх өдрүүдийг «байгаагүй» гэж үзнэ (M5-д эхний борлуулалтаас өмнө тэг бичигдсэн)
first = np.argmax(Y > 0, axis=1)
first[(Y > 0).sum(1) == 0] = Y.shape[1]
alive = np.arange(Y.shape[1])[None, :] >= first[:, None]

month = pd.DatetimeIndex(dates).to_period("M").to_timestamp()
months = pd.date_range("2011-02-01", "2016-05-01", freq="MS")
rows = []
for m in months:
    sel = month == m
    q = Y[:, sel].sum(1)
    days = alive[:, sel].sum(1)
    zero = ((Y[:, sel] == 0) & alive[:, sel]).sum(1)
    rows.append(pd.DataFrame({"id": meta["id"], "month": m, "qty": q, "days": days, "zero_days": zero}))
mon = pd.concat(rows, ignore_index=True)
mon.loc[mon["days"] == 0, "qty"] = np.nan              # бараа хараахан зарагдаагүй сар — тодорхойгүй

# Үнэ: долоо хоногийн үнийг сард дундажлана
pr = pd.read_csv(src / "sell_prices.csv")
wk = cal.groupby("wm_yr_wk")["date"].min().rename("wdate")
pr = pr.merge(wk, left_on="wm_yr_wk", right_index=True)
pr["month"] = pr["wdate"].dt.to_period("M").dt.to_timestamp()
pr["id"] = pr["item_id"] + "_" + pr["store_id"] + "_evaluation"
pm = pr.groupby(["id", "month"])["sell_price"].mean().rename("price").reset_index()
mon = mon.merge(pm, on=["id", "month"], how="left")
mon.to_parquet(out / "m5_monthly.parquet", index=False)
meta.to_parquet(out / "m5_meta.parquet", index=False)
print("сарын мөр", len(mon), "сар", len(months), "NaN сар", int(mon.qty.isna().sum()))

# Системд оруулах өдрийн гүйлгээ: нэг дэлгүүр, ангилал бүрээс борлуулалтын хэмжээгээр тэнцүү алхамтай бараа
st = meta.index[meta.store_id == a.upload_store].to_numpy()
tot = Y[st].sum(1)
pick = []
for cat in sorted(meta.cat_id.unique()):
    ii = st[(meta.cat_id.to_numpy()[st] == cat)]
    ii = ii[np.argsort(-Y[ii].sum(1))]
    k = max(1, round(a.upload_n * len(ii) / len(st)))
    pick += list(ii[np.linspace(0, len(ii) - 1, k).round().astype(int)])
up = out / "upload" / a.upload_store
up.mkdir(parents=True, exist_ok=True)
recs = []
for i in pick:
    nz = np.flatnonzero(Y[i] > 0)
    recs.append(pd.DataFrame({"sale_date": pd.DatetimeIndex(dates[nz]).strftime("%Y-%m-%d"),
                              "item": meta.item_id[i], "category": meta.cat_id[i], "store": meta.store_id[i],
                              "quantity": Y[i, nz]}))
t = pd.concat(recs, ignore_index=True).sort_values(["sale_date", "item"])
t.insert(0, "receipt_no", [f"M5{n:08d}" for n in range(len(t))])
t["uom"] = "ширхэг"
t.to_csv(up / "transactions.csv", index=False)
print("системд оруулах:", len(pick), "бараа,", len(t), "мөр →", up)
