"""
Хуваалт цаг хугацааны дарааллаар: сургалт → validation → тест (сүүлийн бүтэн сараас тоолно).
Эхлэл o = мэдэгдэх сүүлийн сар. Хүрээ k ∈ {1, 3, 12}-ийн хэмжүүрт зөвхөн o + k ≤ хэсгийн төгсгөл
байх эхлэл орно; validation-ийн таамаглал тестийн сарын бодит утгыг хэзээ ч ашиглахгүй.

Сарын алдаа (MAE, RMSE, WAPE, Bias) ба хугацааны нийлбэрийн алдаа (SUM_AE = |Σŷ − Σy|,
SUM_APE = SUM_AE / Σy)-г тусад нь тооцно. Тодорхойгүй хэмжүүрийг 0 эсвэл ∞ болгохгүй.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .monthly import HORIZONS, add_months


@dataclass(frozen=True)
class Splits:
    train_start: pd.Timestamp     # цуваа дор хаяж энэ сараас эхэлсэн байх ёстой
    val_start: pd.Timestamp
    val_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp        # сүүлийн бүтэн сар


def make_splits(last_month: pd.Timestamp, val_months: int = 12, test_months: int = 12,
                train_min: int = 24) -> Splits:
    """Сүүлийн бүтэн сараас хойш: тест = сүүлийн test_months, түүний өмнө validation."""
    test_end = pd.Timestamp(last_month)
    test_start = add_months(test_end, -(test_months - 1))
    val_end = add_months(test_start, -1)
    val_start = add_months(val_end, -(val_months - 1))
    train_start = add_months(val_start, -train_min)
    return Splits(train_start, val_start, val_end, test_start, test_end)


def origins_for(section_start: pd.Timestamp, section_end: pd.Timestamp, step: int = 1) -> list[pd.Timestamp]:
    """o нь хэсгийн өмнөх сараас эхэлж step сараар нэмэгдэнэ; o + 1 ≤ хэсгийн төгсгөл."""
    out = []
    o = add_months(section_start, -1)
    while add_months(o, 1) <= section_end:
        out.append(o)
        o = add_months(o, step)
    return out


def origin_counts(section_start, section_end, step: int = 1, horizons=HORIZONS) -> dict[int, int]:
    """Хүрээ бүрд үнэлэгдэх эхлэлийн тоо (o + k ≤ төгсгөл)."""
    os_ = origins_for(section_start, section_end, step)
    return {k: sum(1 for o in os_ if add_months(o, k) <= section_end) for k in horizons}


def _scale(train: np.ndarray, m: int, power: int) -> tuple[float | None, str | None]:
    """Сургалтын улирлын зөрүүний масштаб (MASE/RMSSE). NaN-тай хосыг алгасна."""
    t = np.asarray(train, dtype=float)
    if len(t) <= m:
        return None, f"n ≤ m ({len(t)} ≤ {m})"
    d = np.abs(t[m:] - t[:-m]) ** power
    d = d[~np.isnan(d)]
    if len(d) == 0:
        return None, f"n ≤ m (ажиглагдсан {m}-сарын зөрүү алга)"
    q = float(np.mean(d))
    if q == 0:
        return None, "масштаб q = 0 (сургалтын улирлын зөрүү бүгд тэг)"
    return q, None


def metrics_for(y: np.ndarray, y_hat: np.ndarray, train: np.ndarray, m: int = 12,
                q_lo: np.ndarray | None = None, q_hi: np.ndarray | None = None,
                tau: tuple[float, float] = (0.1, 0.9)) -> list[dict]:
    """Нэг (цуваа, эхлэл, хүрээ)-ийн хэмжүүр. y-ийн NaN (тодорхойгүй сар)-ийг хосоос хасна."""
    y = np.asarray(y, dtype=float)
    y_hat = np.asarray(y_hat, dtype=float)
    mask = ~np.isnan(y)
    yv, fv = y[mask], y_hat[mask]
    n = int(mask.sum())
    out: list[dict] = []

    def put(metric, value, reason=None):
        out.append({"metric": metric, "value": None if value is None else float(value),
                    "n_pairs": n, "undefined_reason": reason if value is None else None})

    if n == 0:
        for mtr in ("MAE", "RMSE", "Bias", "WAPE", "MASE", "RMSSE", "SUM_AE", "SUM_APE"):
            put(mtr, None, "харьцуулах хос алга (бүх сар тодорхойгүй)")
        return out
    e = fv - yv
    mae = float(np.mean(np.abs(e)))
    put("MAE", mae)
    put("RMSE", float(np.sqrt(np.mean(e ** 2))))
    put("Bias", float(np.mean(e)))
    s = float(np.sum(np.abs(yv)))
    put("WAPE", float(np.sum(np.abs(e)) / s) if s > 0 else None,
        None if s > 0 else "Σ|y| = 0 (бодит утга бүгд тэг)")
    q1, r1 = _scale(train, m, 1)
    put("MASE", mae / q1 if q1 else None, r1)
    q2, r2 = _scale(train, m, 2)
    put("RMSSE", float(np.sqrt(np.mean(e ** 2) / q2)) if q2 else None, r2)
    sum_ae = abs(float(np.sum(fv)) - float(np.sum(yv)))      # хугацааны нийлбэрийн алдаа (2.2)
    put("SUM_AE", sum_ae)
    sy = float(np.sum(yv))
    put("SUM_APE", sum_ae / sy if sy > 0 else None, None if sy > 0 else "Σy = 0")
    if q_lo is not None and q_hi is not None and not np.all(np.isnan(np.asarray(q_lo, dtype=float))):
        lo, hi = np.asarray(q_lo, dtype=float)[mask], np.asarray(q_hi, dtype=float)[mask]
        pin = 0.0
        for q, t in ((lo, tau[0]), (hi, tau[1])):
            d = yv - q
            pin += float(np.mean(np.maximum(t * d, (t - 1) * d)))
        put("PINBALL", pin / 2)
        put("COVERAGE", float(np.mean((yv >= lo) & (yv <= hi))))
        put("WIDTH", float(np.mean(hi - lo)))
    return out


def aggregate_over_origins(rows: pd.DataFrame) -> pd.DataFrame:
    """Эхлэлүүдийн дундаж (origin_date = NULL мөр). Нэг ч тодорхой утга байхгүй бол шалтгаантай."""
    out = []
    if rows.empty:
        return pd.DataFrame(out)
    for (run_id, sid, split, hz, metric), g in rows.groupby(
            ["run_id", "series_id", "split", "horizon", "metric"], sort=False):
        vals = g["value"].dropna()
        n_pairs = int(g["n_pairs"].sum())
        if len(vals):
            out.append({"run_id": run_id, "series_id": sid, "split": split, "horizon": hz,
                        "metric": metric, "origin_date": None, "value": float(vals.mean()),
                        "n_pairs": n_pairs,
                        "undefined_reason": None if len(vals) == len(g) else
                        f"{len(g) - len(vals)}/{len(g)} эхлэлд тодорхойгүй — үлдсэний дундаж"})
        else:
            reasons = "; ".join(sorted(set(g["undefined_reason"].dropna())))[:300]
            out.append({"run_id": run_id, "series_id": sid, "split": split, "horizon": hz,
                        "metric": metric, "origin_date": None, "value": None, "n_pairs": n_pairs,
                        "undefined_reason": reasons or "тодорхойгүй"})
    return pd.DataFrame(out)
