"""scripts/load_m5.py: M5-ын эх хэлбэртэй жижиг өгөгдлийг хөрвүүлж, системийн ingest/grid-ээр шалгана."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fcsys.engine import grid, ingest
from fcsys.engine.protocol import MIN_FULL_MONTHS

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("load_m5", ROOT / "scripts" / "load_m5.py")
load_m5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(load_m5)

N_DAYS = 700
START = pd.Timestamp("2011-01-29")     # M5-ын d_1


@pytest.fixture(scope="module")
def m5_src(tmp_path_factory):
    src = tmp_path_factory.mktemp("m5")
    dates = pd.date_range(START, periods=N_DAYS, freq="D")
    wk = 11101 + (np.arange(N_DAYS) // 7)
    pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "wm_yr_wk": wk,
                  "d": [f"d_{i}" for i in range(1, N_DAYS + 1)]}).to_csv(src / "calendar.csv", index=False)
    rng = np.random.default_rng(0)
    rows, prices = [], []
    items = [("FOODS_3_001", "FOODS_3", "FOODS"), ("FOODS_3_002", "FOODS_3", "FOODS"),
             ("HOBBIES_1_001", "HOBBIES_1", "HOBBIES"), ("HOBBIES_1_002", "HOBBIES_1", "HOBBIES")]
    for store in ("CA_1", "TX_1"):
        for item, dept, cat in items:
            lam = 3.0 if cat == "FOODS" else 0.3                 # HOBBIES = ховор (intermittent)
            q = rng.poisson(lam, N_DAYS)
            if item == "HOBBIES_1_002":
                q[:200] = 0                                       # хожим гарсан бараа
            q[(dates.month == 12) & (dates.day == 25)] = 0        # Зул сар: хаалттай
            rows.append([f"{item}_{store}_evaluation", item, dept, cat, store, store[:2], *q])
            launch = 200 // 7 if item == "HOBBIES_1_002" else 0
            for w in np.unique(wk)[launch:]:
                prices.append([store, item, w, 2.5 if cat == "FOODS" else 9.99])
    cols = load_m5.ID_COLS + [f"d_{i}" for i in range(1, N_DAYS + 1)]
    pd.DataFrame(rows, columns=cols).to_csv(src / "sales_train_evaluation.csv", index=False)
    pd.DataFrame(prices, columns=["store_id", "item_id", "wm_yr_wk", "sell_price"]).to_csv(
        src / "sell_prices.csv", index=False)
    return src


@pytest.fixture(scope="module")
def converted(m5_src, tmp_path_factory):
    out = tmp_path_factory.mktemp("m5_upload")
    manifest = load_m5.convert(m5_src, out, stores=["CA_1"], n_items=0)
    return out, manifest


def test_filters_and_manifest(converted):
    out, m = converted
    assert m["stores"] == ["CA_1"] and m["series"] == 4
    assert m["full_months"] >= MIN_FULL_MONTHS
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8"))["series"] == 4


def test_mapping_is_suggested_automatically(converted):
    out, _ = converted
    cols = list(pd.read_csv(out / "transactions.csv", nrows=1).columns)
    m = ingest.suggest_mapping(cols)
    assert m["txn_date"] == "sale_date" and m["product_id"] == "item" and m["qty"] == "quantity"
    assert m["branch_id"] == "store" and m["unit"] == "uom" and m["amount"] == "revenue"
    assert m["product_category"] == "category" and m["txn_id"] == "receipt_no"
    assert not ingest.missing_required(cols, m)


def test_quantities_and_revenue_match_source(converted, m5_src):
    out, _ = converted
    tx = pd.read_csv(out / "transactions.csv")
    src = pd.read_csv(m5_src / "sales_train_evaluation.csv")
    day_cols = [c for c in src.columns if c.startswith("d_")]
    assert tx["quantity"].sum() == src[src.store_id == "CA_1"][day_cols].to_numpy().sum()
    assert (tx["quantity"] > 0).all() and tx["receipt_no"].is_unique
    foods = tx[tx["item"].str.startswith("FOODS")]
    assert np.allclose(foods["revenue"], foods["quantity"] * 2.5)


def test_aux_files_parse(converted):
    out, _ = converted
    price = ingest.parse_aux("price", out / "price.csv")
    cal = ingest.parse_aux("calendar", out / "calendar.csv")
    assert set(price["price_kind"]) == {"actual"}
    xmas = cal[(cal["date"].dt.month == 12) & (cal["date"].dt.day == 25)]
    assert len(xmas) >= 1 and not xmas["is_open"].any()


def test_daily_grid_states(converted):
    out, _ = converted
    raw = pd.read_csv(out / "transactions.csv", dtype=str)
    tx = ingest.parse_transactions(raw, ingest.suggest_mapping(list(raw.columns)))
    cal = ingest.parse_aux("calendar", out / "calendar.csv")
    daily = grid.build_daily(tx, tx["txn_date"].max(), calendar=cal)
    # Зул сар → closed (зорилтоос хасагдана), 0 гэж тооцохгүй
    xmas = daily[(daily["day"].dt.month == 12) & (daily["day"].dt.day == 25)]
    assert (xmas["day_state"] == "closed").all()
    # Хожим гарсан бараа анхны борлуулалтаас эхэлнэ (зохиомол 0 нэмэгдэхгүй)
    late = daily[daily["product_id"] == "HOBBIES_1_002"]
    assert late["day"].min() >= START + pd.Timedelta(days=200)
    assert daily.groupby("product_id")["sales_qty"].sum().sum() == tx["qty"].sum()
