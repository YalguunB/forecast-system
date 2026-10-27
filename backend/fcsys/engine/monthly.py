"""monthly — сарын цуваа ба хугацааны нийлбэр (диплом §2.4, тэгшитгэл 2.1, 2.2; MonthlySeriesBuilder, PeriodResolver).

Өдрийн цуваа (өдрийн төлөвтэй) нь өгөгдлийн чанарын суурь хэвээр; таамаглал сарын түвшинд хийгдэнэ:

    Y[p, b, m] = Σ өдрийн борлуулалт, d ∈ m                                    (2.1)
    Ŷ[хугацаа] = Σ_{h=1..k} Ŷ[m+h],  k = 1 (сар), 3 (улирал), 12 (жил)            (2.2)

Дүрэм:
* Дутуу сарыг бүтэн сар гэж үзэхгүй: цуваа сарын дундаас эхэлсэн эсвэл өгөгдөл сарын дундуур
  дууссан бол тэр сар цуваанд орохгүй.
* Салбарт тухайн сард нэг ч гүйлгээ бүртгэгдээгүй (бүх өдөр «бүртгэл дутуу» / «хаалттай») бол
  сарын утга тодорхойгүй (NaN) — 0 гэж үзэхгүй.
* Эрэлтийн (D) зорилтод нөөцгүй өдөр сарын 20%-иас олон бол сарын эрэлт халхлагдсан тул NaN.
* Интервалын хязгаарыг нэмж улирал, жилийн интервал гэж үзэхгүй (нийлбэрт зөвхөн цэгэн таамаглал).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (1, 3, 12)
PERIODS = {"month": 1, "quarter": 3, "year": 12}
PERIOD_LABELS = {1: "Сар", 3: "Улирал", 12: "Жил"}
GAP_STATES = ("missing", "closed")
CENSOR_SHARE = 0.2


def month_start(ts) -> pd.Timestamp:
    return pd.Timestamp(ts).to_period("M").to_timestamp()


def add_months(ts, k: int) -> pd.Timestamp:
    return month_start(ts) + pd.DateOffset(months=int(k))


def months_between(a, b) -> int:
    """b − a сараар (хоёулаа сарын эхлэл)."""
    a, b = pd.Timestamp(a), pd.Timestamp(b)
    return (b.year - a.year) * 12 + (b.month - a.month)


def last_complete_month(date_max) -> pd.Timestamp:
    """Өгөгдлийн сүүлийн бүтэн сар. date_max сарын сүүлийн өдөр биш бол өмнөх сар."""
    dm = pd.Timestamp(date_max)
    return month_start(dm) if dm.is_month_end else add_months(dm, -1)


def resolve_period(period: str | int) -> int:
    """PeriodResolver: 'month' | 'quarter' | 'year' (эсвэл 1/3/12) → зорилтот сарын тоо."""
    if isinstance(period, str) and period in PERIODS:
        return PERIODS[period]
    k = int(period)
    if k not in HORIZONS:
        raise ValueError(f"Хугацаа {period}: сар (1), улирал (3), жил (12)-ийн аль нэг байна")
    return k


def build_monthly(daily: pd.DataFrame, target: str, date_max) -> pd.DataFrame:
    """MonthlySeriesBuilder: нэг цувааны өдрийн мөрөөс (day, sales_qty, day_state) сарын хүснэгт.

    Буцаах багана (index = сарын эхлэл, давтамж MS): y, n_days, n_gap, n_stockout, reason.
    y = NaN бол reason-д шалтгаан бичигдэнэ. Эхний дутуу сар хүснэгтэд орохгүй."""
    cols = ["y", "n_days", "n_gap", "n_stockout", "reason"]
    last = last_complete_month(date_max)
    if daily is None or daily.empty:
        return pd.DataFrame(columns=cols)
    d = daily[daily["day"] < add_months(last, 1)]
    if d.empty:
        return pd.DataFrame(columns=cols)
    first_day = pd.Timestamp(d["day"].iloc[0])
    first = month_start(first_day) if first_day.day == 1 else add_months(first_day, 1)
    if first > last:
        return pd.DataFrame(columns=cols)
    d = d[d["day"] >= first]
    m = d["day"].dt.to_period("M").dt.to_timestamp()
    state = d["day_state"].values
    qty = d["sales_qty"].astype(float).values
    stock = state == "stockout"
    frame = pd.DataFrame({"m": m.values, "qty": qty, "gap": np.isin(state, GAP_STATES), "stock": stock,
                          "qty_nostock": np.where(stock, 0.0, qty)})
    g = frame.groupby("m").agg(qty=("qty", "sum"), n_days=("qty", "size"), n_gap=("gap", "sum"),
                               n_stockout=("stock", "sum"))
    idx = pd.date_range(first, last, freq="MS")
    g = g.reindex(idx)
    g["n_days"] = g["n_days"].fillna(0).astype(int)
    g["n_gap"] = g["n_gap"].fillna(0).astype(int)
    g["n_stockout"] = g["n_stockout"].fillna(0).astype(int)
    dim = idx.days_in_month.values
    y = g["qty"].astype(float).values.copy()
    reason = np.full(len(g), None, dtype=object)
    incomplete = g["n_days"].values < dim
    y[incomplete] = np.nan
    reason[incomplete] = "дутуу сар (өдөр дутуу)"
    no_records = (~incomplete) & (g["n_gap"].values >= g["n_days"].values)
    y[no_records] = np.nan
    reason[no_records] = "сард гүйлгээ бүртгэгдээгүй"
    if target == "demand":
        cens = (~incomplete) & (~no_records) & (g["n_stockout"].values > CENSOR_SHARE * dim)
        y[cens] = np.nan
        reason[cens] = f"нөөцгүй өдөр {int(CENSOR_SHARE * 100)}%-иас олон (эрэлт халхлагдсан)"
    out = pd.DataFrame({"y": y, "n_days": g["n_days"].values, "n_gap": g["n_gap"].values,
                        "n_stockout": g["n_stockout"].values, "reason": reason}, index=idx)
    out.index.name = "month"
    return out


def monthly_target(daily: pd.DataFrame, target: str, date_max) -> pd.Series:
    """Загварт орох сарын зорилт (NaN = тодорхойгүй сар). Index давтамж MS."""
    t = build_monthly(daily, target, date_max)
    s = pd.Series(t["y"].astype(float).values if len(t) else [], index=pd.DatetimeIndex(t.index, freq="MS")
                  if len(t) else pd.DatetimeIndex([]), name="y", dtype=float)
    return s


def period_totals(y_hat, horizons=HORIZONS) -> dict[int, float]:
    """(2.2): сар, улирал, жилийн нийлбэр = эхний k сарын цэгэн таамаглалын нийлбэр."""
    v = np.asarray(y_hat, dtype=float)
    return {k: float(v[:k].sum()) for k in horizons if len(v) >= k}
