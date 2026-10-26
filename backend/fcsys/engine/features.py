"""features — эхлэл o-д мэдэгдэх мэдээллээр шинж үүсгэх (FR-S3, FR-S4, Z3, Хүснэгт 4.8).

Бүх функц эхлэл o-г заавал авч, түүнээс хойших өдрийг хэзээ ч уншихгүй. Үнэ зөвхөн
known_at ≤ o мөрөөр орно. Мэдээллийн алдагдлын тест (tests/test_leakage.py) үүнийг шалгана.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LAGS = (1, 7, 14, 28)
WINDOWS = (7, 14, 30)

# Шинж бүрийн хүртээмжийн тэмдэг (FR-S4): known_at_origin | scenario | unknown
FEATURE_AVAILABILITY = {
    **{f"lag_{k}": "known_at_origin" for k in LAGS},
    **{f"roll_mean_{w}": "known_at_origin" for w in WINDOWS},
    **{f"roll_std_{w}": "known_at_origin" for w in WINDOWS},
    "dow": "known_at_origin", "month": "known_at_origin", "is_holiday": "known_at_origin",
    "is_open": "known_at_origin",
    "price_approved": "known_at_origin",   # «батлагдсан төлөвлөгөө», known_at ≤ o
    "price_scenario": "scenario",          # тусдаа туршилтад л
    "price_actual_future": "unknown",      # ирээдүйн бодит үнэ — оролтод ХЭЗЭЭ Ч орохгүй
}
FEATURE_SETS = {
    "L": [f"lag_{k}" for k in LAGS] + [f"roll_mean_{w}" for w in WINDOWS] + [f"roll_std_{w}" for w in WINDOWS],
}
FEATURE_SETS["LC"] = FEATURE_SETS["L"] + ["dow", "month", "is_holiday", "is_open"]
FEATURE_SETS["LCP"] = FEATURE_SETS["LC"] + ["price_approved"]


def history_until(y: pd.Series, origin: pd.Timestamp) -> pd.Series:
    """Z3: зөвхөн day ≤ o мөр."""
    return y.loc[:origin]


def fill_for_model(y: pd.Series) -> pd.Series:
    """Зорилтоос хасагдсан (NaN: хаалттай, бүртгэл дутуу) өдрийг загварын оролтод нөхнө.
    Зөвхөн өмнөх утгыг ашиглана: долоо хоногийн ижил өдрийн сүүлийн 4 ажиглалтын дундаж,
    байхгүй бол сүүлийн ажиглалт. Нөхсөн утга үнэлгээнд хэзээ ч орохгүй."""
    y = y.copy()
    first = y.first_valid_index()
    if first is None:
        return y.fillna(0.0)
    y = y.loc[first:]
    vals = y.values.astype(float)
    for i in np.where(np.isnan(vals))[0]:
        same_dow = [vals[j] for j in range(i - 7, max(-1, i - 7 * 5), -7) if j >= 0 and not np.isnan(vals[j])]
        if same_dow:
            vals[i] = float(np.mean(same_dow[:4]))
        else:
            prev = vals[:i][~np.isnan(vals[:i])]
            vals[i] = float(prev[-1]) if len(prev) else 0.0
    return pd.Series(vals, index=y.index, name=y.name)


def known_prices(prices: pd.DataFrame | None, origin: pd.Timestamp) -> pd.DataFrame:
    """FR-S4, DQ-10: known_at ≤ o, «бодит» үнэ зөвхөн хүчинтэй болсон нь (date ≤ o)."""
    if prices is None or prices.empty:
        return pd.DataFrame(columns=["date", "price", "price_kind", "known_at"])
    p = prices[prices["known_at"] <= origin]
    p = p[(p["price_kind"] != "actual") | (p["date"] <= origin)]
    return p[p["price_kind"] != "scenario"]


def build_features(y: pd.Series, origin: pd.Timestamp, horizon: int,
                   holidays: set | None = None, calendar_open: pd.Series | None = None,
                   prices: pd.DataFrame | None = None) -> pd.DataFrame:
    """Эхлэл o-оос h = 1..H зорилтот өдөр бүрийн шинжийн мөр (direct хэлбэр).
    Хоцролт, гулсах статистик o-д (t−1 хүртэл) дуусна; календарь ирээдүйд мэдэгдэнэ."""
    hist = fill_for_model(history_until(y, origin))
    rows = []
    kp = known_prices(prices, origin)
    approved = kp[kp["price_kind"] == "approved_plan"].sort_values("date")
    last_actual = kp[kp["price_kind"] == "actual"].sort_values("date")
    for h in range(1, horizon + 1):
        target = origin + pd.Timedelta(days=h)
        r = {"h": h, "target_date": target}
        for k in LAGS:
            # y(t−k) нь o-оос хойш бол мэдэгдэхгүй → хамгийн сүүлийн мэдэгдэх утга (o-д тогтсон)
            src = target - pd.Timedelta(days=k)
            src = min(src, origin)
            r[f"lag_{k}"] = float(hist.get(src, np.nan))
        for w in WINDOWS:
            win = hist.loc[origin - pd.Timedelta(days=w - 1):origin]
            r[f"roll_mean_{w}"] = float(win.mean()) if len(win) else np.nan
            r[f"roll_std_{w}"] = float(win.std(ddof=0)) if len(win) else np.nan
        r["dow"] = target.dayofweek
        r["month"] = target.month
        r["is_holiday"] = int(bool(holidays) and target.date() in holidays)
        r["is_open"] = (int(bool(calendar_open.get(target, True))) if calendar_open is not None else 1)
        ap = approved[approved["date"] <= target]
        if len(ap):
            r["price_approved"] = float(ap["price"].iloc[-1])
        elif len(last_actual):
            r["price_approved"] = float(last_actual["price"].iloc[-1])
        else:
            r["price_approved"] = np.nan
        rows.append(r)
    return pd.DataFrame(rows)
