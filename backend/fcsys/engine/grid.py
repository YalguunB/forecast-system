"""grid — бүтээгдэхүүн–салбар–өдрийн цуваа, өдрийн төлөв, зорилт (FR-D5, FR-S1, §3.8).

Гүйлгээгүй өдрийг автоматаар 0 болгохгүй: өдөр бүрд Хүснэгт 3.8-ын төлвийн нэгийг
оноож, зорилт (S эсвэл D) тухайн төлвөөр тодорхойлогдоно.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DAY_STATES = ["sold", "open_no_sale", "stockout", "closed", "missing", "unknown"]

# Зорилтод орох эсэх (Хүснэгт 3.8-ын сүүлийн багана). None = зорилтоос хасна (NaN).
TARGET_RULES = {
    "sales":  {"sold": "qty", "open_no_sale": 0.0, "stockout": 0.0, "unknown": 0.0,
               "closed": None, "missing": None},
    # Эрэлт D: нөөцгүй өдөр халхлагдсан (censored) тул ажиглагдсан утга эрэлт биш → хасна.
    "demand": {"sold": "qty", "open_no_sale": 0.0, "stockout": None, "unknown": 0.0,
               "closed": None, "missing": None},
}

TARGET_LABELS = {"sales": "Борлуулалтын таамаглал", "demand": "Эрэлтийн таамаглал"}


def convert_units(tx: pd.DataFrame, conversions: list[dict] | None) -> pd.DataFrame:
    """Нэгжийн хөрвүүлэлт (FR-D3). conversions: [{product_id|'*', from, to, factor}]."""
    if not conversions:
        return tx
    tx = tx.copy()
    for c in conversions:
        mask = tx["unit"] == c["from"]
        if c.get("product_id", "*") != "*":
            mask &= tx["product_ext_id"] == c["product_id"]
        tx.loc[mask, "qty"] = tx.loc[mask, "qty"] * float(c["factor"])
        tx.loc[mask, "unit"] = c["to"]
    return tx


def build_daily(tx: pd.DataFrame, date_max: pd.Timestamp,
                calendar: pd.DataFrame | None = None,
                inventory: pd.DataFrame | None = None) -> pd.DataFrame:
    """tx: цэвэр мөрүүд (карантингүй). Буцаах багана: product_id, branch_id, unit, day,
    sales_qty, returns_qty, sales_amount, day_state."""
    if tx.empty:
        return pd.DataFrame(columns=["product_id", "branch_id", "unit", "day", "sales_qty",
                                     "returns_qty", "sales_amount", "day_state"])
    t = tx.copy()
    t["sold"] = np.where(t["is_return"], 0.0, t["qty"].clip(lower=0))
    t["ret"] = np.where(t["is_return"], t["qty"].abs(), 0.0)
    t["amt"] = np.where(t["is_return"], -t["amount"].abs(), t["amount"])
    agg = (t.groupby(["product_ext_id", "branch_ext_id", "txn_date"])
             .agg(sold=("sold", "sum"), ret=("ret", "sum"), amt=("amt", "sum"), n=("qty", "size"))
             .reset_index())
    units = t.groupby("product_ext_id")["unit"].agg(lambda s: s.mode().iloc[0])

    # салбар бүрийн өдрийн гүйлгээний тоо — салбар бүхэлдээ гүйлгээгүй өдөр = бүртгэл дутуу
    branch_active = t.groupby(["branch_ext_id", "txn_date"]).size()

    cal = None
    if calendar is not None and len(calendar):
        cal = calendar.set_index(["branch_id", "date"])["is_open"]
    inv = None
    if inventory is not None and len(inventory):
        inv = inventory.set_index(["product_id", "branch_id", "date"])

    # Салбарын бүртгэл эхэлсэн өдөр. Бүтээгдэхүүн бүртгэлийн эхний сард зарагдсан бол түүх нь бүртгэлийн
    # эхнээс эхэлнэ: эхний борлуулалт 1-нд биш 3-нд болсон нь тэр сарыг «дутуу» болгох шалтгаан биш
    # (өмнө нь эхний сар хасагдаж, 48 сарын шаардлагад хүрэхгүй бараа туршилтаас унадаг байв).
    # Хожим гарсан бүтээгдэхүүний түүх анхны борлуулалтаас эхэлсэн хэвээр (зохиомол 0 нэмэхгүй).
    branch_first = t.groupby("branch_ext_id")["txn_date"].min()

    frames = []
    for (pid, bid), g in agg.groupby(["product_ext_id", "branch_ext_id"], sort=True):
        start = g["txn_date"].min()
        b0 = branch_first.get(bid)
        if b0 is not None and b0 < start and b0.to_period("M") == start.to_period("M"):
            start = b0
        days = pd.date_range(start, date_max, freq="D")
        f = pd.DataFrame({"day": days})
        f = f.merge(g.rename(columns={"txn_date": "day"})[["day", "sold", "ret", "amt"]],
                    on="day", how="left")
        net = (f["sold"].fillna(0) - f["ret"].fillna(0)).clip(lower=0)
        f["sales_qty"] = net
        f["returns_qty"] = f["ret"].fillna(0)
        f["sales_amount"] = f["amt"]
        state = np.full(len(f), "unknown", dtype=object)
        state[net.values > 0] = "sold"
        no_sale = net.values <= 0

        if inv is not None:
            idx = pd.MultiIndex.from_arrays([[pid] * len(f), [bid] * len(f), f["day"]])
            sub = inv.reindex(idx)
            avail = sub["available"].values
            onhand = sub["on_hand"].values if "on_hand" in sub else np.full(len(f), np.nan)
            known = pd.notna(avail)
            out_of_stock = known & ((avail == False) | (pd.notna(onhand) & (onhand <= 0)))  # noqa: E712
            in_stock = known & ~out_of_stock
            state[no_sale & out_of_stock] = "stockout"
            state[no_sale & in_stock] = "open_no_sale"

        b_active = branch_active.reindex(
            pd.MultiIndex.from_arrays([[bid] * len(f), f["day"]])).fillna(0).values
        state[no_sale & (b_active == 0)] = "missing"

        if cal is not None:
            is_open = cal.reindex(pd.MultiIndex.from_arrays([[bid] * len(f), f["day"]])).values
            closed = pd.notna(is_open) & (is_open == False)  # noqa: E712
            state[no_sale & closed] = "closed"
            # салбар нээлттэй гэж батлагдсан ч бүх бүтээгдэхүүн гүйлгээгүй → бүртгэл дутуу хэвээр
        f["day_state"] = state
        f["product_id"] = pid
        f["branch_id"] = bid
        f["unit"] = units.get(pid, "")
        frames.append(f[["product_id", "branch_id", "unit", "day", "sales_qty", "returns_qty",
                         "sales_amount", "day_state"]])
    return pd.concat(frames, ignore_index=True)


def target_series(daily: pd.DataFrame, target: str) -> pd.Series:
    """Өдрийн төлвөөс зорилтын утга (NaN = зорилтоос хасагдсан өдөр). daily нэг цуваа, day-ээр эрэмбэлсэн."""
    rules = TARGET_RULES[target]
    vals = np.empty(len(daily))
    for st, rule in rules.items():
        m = (daily["day_state"] == st).values
        if rule is None:
            vals[m] = np.nan
        elif rule == "qty":
            vals[m] = daily["sales_qty"].values[m]
        else:
            vals[m] = rule
    return pd.Series(vals, index=pd.DatetimeIndex(daily["day"]), name="y")
