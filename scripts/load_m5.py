"""M5 (Walmart) нээлттэй өгөгдлийг системийн оруулах файлын хэлбэрт хөрвүүлэх.

Эх файлууд (Kaggle «M5 Forecasting - Accuracy»):
    calendar.csv, sell_prices.csv, sales_train_evaluation.csv (эсвэл sales_train_validation.csv)

Гаралт (data/demand_test/upload-тэй ижил хэлбэр, «Өгөгдөл оруулах» дэлгэцээр шууд оруулна):
    transactions.csv  — бараа × дэлгүүр × өдөр бүрийн нэг мөр (зөвхөн qty > 0). M5 нь баримтын түвшний
                        биш, өдрийн нийлбэр тул receipt_no нь зохиомол.
    price.csv         — өдрийн үнэ (sell_prices-ийн 7 хоногийн үнийг өдөр бүрд тараасан), price_kind=actual
    calendar.csv      — дэлгүүрийн нээлттэй эсэх: 12-р сарын 25-нд M5-ын бүх дэлгүүр хаалттай (борлуулалт 0)
    manifest.json     — эх файлын sha256, шүүлтүүр, мөрийн тоо

M5 нөөцийн (inventory) мэдээлэлгүй: урт тасалдлыг систем өөрөө «stockout_est» гэж тооцоолно.

Жишээ:
    python scripts/load_m5.py --src ~/m5 --out data/m5_upload --stores CA_1 --depts FOODS_3 --items 300
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ID_COLS = ["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"]
UNIT = "ширхэг"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def full_months(d0: pd.Timestamp, d1: pd.Timestamp) -> int:
    """[d0, d1] хүрээнд бүтнээрээ орсон сарын тоо."""
    first = d0.to_period("M") + (0 if d0.day == 1 else 1)
    last = d1.to_period("M") - (0 if d1.is_month_end else 1)
    return max(0, (last - first).n + 1)


def find_sales_file(src: Path) -> Path:
    for name in ("sales_train_evaluation.csv", "sales_train_validation.csv"):
        if (src / name).exists():
            return src / name
    raise FileNotFoundError(f"{src}-д sales_train_evaluation.csv эсвэл sales_train_validation.csv алга")


def select_series(sales: pd.DataFrame, stores, depts, cats, n_items, sample, seed) -> pd.DataFrame:
    s = sales
    if stores:
        s = s[s["store_id"].isin(stores)]
    if depts:
        s = s[s["dept_id"].isin(depts)]
    if cats:
        s = s[s["cat_id"].isin(cats)]
    if s.empty:
        raise ValueError("Шүүлтүүрт тохирох цуваа алга (--stores/--depts/--cats-ийг шалгана уу)")
    if n_items and s["item_id"].nunique() > n_items:
        items = s["item_id"].drop_duplicates()
        if sample == "top":
            day_cols = [c for c in s.columns if c.startswith("d_")]
            tot = pd.Series(s[day_cols].to_numpy().sum(axis=1), index=s["item_id"].values).groupby(level=0).sum()
            keep = tot.sort_values(ascending=False).index[:n_items]
        else:
            keep = items.sample(n=n_items, random_state=seed)
        s = s[s["item_id"].isin(set(keep))]
    return s


def convert(src: Path, out: Path, stores=None, depts=None, cats=None, n_items=300, sample="random",
            seed=7, start=None, end=None) -> dict:
    sales_path = find_sales_file(src)
    cal = pd.read_csv(src / "calendar.csv", usecols=["date", "wm_yr_wk", "d"], parse_dates=["date"])
    sales = pd.read_csv(sales_path)
    sales = select_series(sales, stores, depts, cats, n_items, sample, seed)

    day_cols = [c for c in sales.columns if c.startswith("d_")]
    long = sales.melt(id_vars=ID_COLS, value_vars=day_cols, var_name="d", value_name="qty")
    long = long.merge(cal, on="d", how="left")
    if long["date"].isna().any():
        raise ValueError("calendar.csv-д байхгүй d_ багана байна — файлууд нэг хувилбарынх эсэхийг шалгана уу")
    if start:
        long = long[long["date"] >= pd.Timestamp(start)]
    if end:
        long = long[long["date"] <= pd.Timestamp(end)]
    date_min, date_max = long["date"].min(), long["date"].max()

    # Үнэ: 7 хоногийн үнийг өдөр бүрд
    prices = pd.read_csv(src / "sell_prices.csv")
    prices = prices[prices["store_id"].isin(sales["store_id"].unique())
                    & prices["item_id"].isin(sales["item_id"].unique())]
    daily_price = (cal[(cal["date"] >= date_min) & (cal["date"] <= date_max)][["date", "wm_yr_wk"]]
                   .merge(prices, on="wm_yr_wk", how="inner"))

    tx = long[long["qty"] > 0].merge(daily_price[["date", "store_id", "item_id", "sell_price"]],
                                     on=["date", "store_id", "item_id"], how="left")
    tx = tx.sort_values(["date", "store_id", "item_id"]).reset_index(drop=True)
    transactions = pd.DataFrame({
        "receipt_no": [f"M5-{i:09d}" for i in range(1, len(tx) + 1)],
        "sale_date": tx["date"].dt.strftime("%Y-%m-%d"),
        "item": tx["item_id"],
        "category": tx["dept_id"],
        "store": tx["store_id"],
        "quantity": tx["qty"].astype(int),
        "uom": UNIT,
        "revenue": (tx["qty"] * tx["sell_price"]).round(2),
        "is_return": 0,
    })

    price = pd.DataFrame({
        "date": daily_price["date"].dt.strftime("%Y-%m-%d"),
        "product_id": daily_price["item_id"],
        "branch_id": daily_price["store_id"],
        "price": daily_price["sell_price"].round(2),
        "price_kind": "actual",
    }).sort_values(["date", "branch_id", "product_id"])

    days = pd.date_range(date_min, date_max, freq="D")
    calendar = pd.DataFrame([(d.strftime("%Y-%m-%d"), s, 0 if (d.month == 12 and d.day == 25) else 1)
                             for s in sorted(sales["store_id"].unique()) for d in days],
                            columns=["date", "branch_id", "is_open"])

    out.mkdir(parents=True, exist_ok=True)
    transactions.to_csv(out / "transactions.csv", index=False)
    price.to_csv(out / "price.csv", index=False)
    calendar.to_csv(out / "calendar.csv", index=False)

    n_series = sales[["item_id", "store_id"]].drop_duplicates().shape[0]
    zero_share = float((long["qty"] == 0).mean())
    manifest = {
        "source": "M5 Forecasting - Accuracy (Walmart), Kaggle / Makridakis et al. 2022, IJF 38(4)",
        "source_files": {p.name: sha256(p) for p in (sales_path, src / "calendar.csv", src / "sell_prices.csv")},
        "filters": {"stores": stores, "depts": depts, "cats": cats, "items": n_items, "sample": sample,
                    "seed": seed, "start": start, "end": end},
        "date_min": str(date_min.date()), "date_max": str(date_max.date()),
        "full_months": full_months(date_min, date_max),
        "series": n_series,
        "items": int(sales["item_id"].nunique()),
        "stores": sorted(sales["store_id"].unique().tolist()),
        "rows": {"transactions": len(transactions), "price": len(price), "calendar": len(calendar)},
        "zero_day_share": round(zero_share, 4),
        "notes": [
            "transactions = өдрийн нийлбэр (M5 нь баримтын түвшний биш); receipt_no зохиомол",
            "inventory.csv алга: M5-д нөөцийн мэдээлэл байхгүй",
            "12-р сарын 25 = хаалттай (calendar.csv)",
            "Бараа гарахаас өмнөх 0-ийг оруулаагүй: цуваа анхны борлуулалтаас эхэлнэ",
        ],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, type=Path, help="M5 CSV файлууд байгаа хавтас")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--stores", nargs="*", default=["CA_1"], help="жишээ: CA_1 TX_2 (хоосон = бүгд)")
    ap.add_argument("--depts", nargs="*", default=None, help="жишээ: FOODS_3 HOBBIES_1")
    ap.add_argument("--cats", nargs="*", default=None, help="FOODS / HOBBIES / HOUSEHOLD")
    ap.add_argument("--items", type=int, default=300, help="барааны дээд тоо (0 = бүгд)")
    ap.add_argument("--sample", choices=["random", "top"], default="random",
                    help="random: санамсаргүй (ховор бараа орно), top: хамгийн их зарагдсан")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--start", help="YYYY-MM-DD")
    ap.add_argument("--end", help="YYYY-MM-DD")
    a = ap.parse_args(argv)
    m = convert(a.src, a.out, a.stores or None, a.depts, a.cats, a.items, a.sample, a.seed, a.start, a.end)
    print(json.dumps({k: m[k] for k in ("date_min", "date_max", "full_months", "series", "rows",
                                        "zero_day_share")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
