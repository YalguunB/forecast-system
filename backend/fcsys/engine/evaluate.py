"""evaluate — гүйдэг эхлэлтэй үнэлгээ ба хэмжүүр (FR-M3, FR-E1, FR-E2, FR-E4, §4.4).

Тодорхойгүй хэмжүүрийг 0 эсвэл ∞ болгохгүй: утга None, шалтгаан undefined_reason-д.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

HORIZONS = (7, 14, 30)


@dataclass(frozen=True)
class Splits:
    train_start: pd.Timestamp
    val_start: pd.Timestamp
    val_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def make_splits(date_max: pd.Timestamp, val_days: int = 60, test_days: int = 90,
                train_min: int = 180) -> Splits:
    """Өгөгдлийн төгсгөлөөс хойш тест (сүүлийн test_days), түүний өмнө validation."""
    test_end = pd.Timestamp(date_max)
    test_start = test_end - pd.Timedelta(days=test_days - 1)
    val_end = test_start - pd.Timedelta(days=1)
    val_start = val_end - pd.Timedelta(days=val_days - 1)
    train_start = val_start - pd.Timedelta(days=train_min)
    return Splits(train_start, val_start, val_end, test_start, test_end)


def origins_for(section_start: pd.Timestamp, section_end: pd.Timestamp,
                step: int = 7, H: int = 30) -> list[pd.Timestamp]:
    """o нь хэсгийн өмнөх өдрөөс эхэлж step-ээр нэмэгдэнэ; o + H хэсгээс хэтрэхгүй.
    Анхдагч протоколд validation (60) → 5, тест (90) → 9 эхлэл."""
    out = []
    o = section_start - pd.Timedelta(days=1)
    while o + pd.Timedelta(days=H) <= section_end:
        out.append(o)
        o += pd.Timedelta(days=step)
    return out


def _scale(train: np.ndarray, m: int, power: int) -> tuple[float | None, str | None]:
    """Сургалтын улирлын зөрүүний масштаб. t ба t−m өдрийн аль нэг нь хасагдсан (NaN)
    бол тэр хосыг алгасна (өдрийг шахаж зэрэгцүүлэхгүй)."""
    t = np.asarray(train, dtype=float)
    if len(t) <= m:
        return None, f"n ≤ m ({len(t)} ≤ {m})"
    d = np.abs(t[m:] - t[:-m]) ** power
    d = d[~np.isnan(d)]
    if len(d) == 0:
        return None, f"n ≤ m (ажиглагдсан {m}-хоногийн зөрүү алга)"
    q = float(np.mean(d))
    if q == 0:
        return None, "масштаб q = 0 (сургалтын улирлын зөрүү бүгд тэг)"
    return q, None


def metrics_for(y: np.ndarray, y_hat: np.ndarray, train: np.ndarray, m: int = 7,
                q_lo: np.ndarray | None = None, q_hi: np.ndarray | None = None,
                tau: tuple[float, float] = (0.1, 0.9)) -> list[dict]:
    """Нэг (цуваа, эхлэл, хүрээ)-ийн хэмжүүр. y-ийн NaN (хасагдсан өдөр)-ийг хосоос хасна."""
    mask = ~np.isnan(y)
    yv, fv = y[mask], y_hat[mask]
    n = int(mask.sum())
    out: list[dict] = []

    def put(metric, value, reason=None):
        out.append({"metric": metric, "value": None if value is None else float(value),
                    "n_pairs": n, "undefined_reason": reason if value is None else None})

    if n == 0:
        for mtr in ("MAE", "RMSE", "Bias", "WAPE", "MASE", "RMSSE", "SUM_AE"):
            put(mtr, None, "харьцуулах хос алга (бүх өдөр зорилтоос хасагдсан)")
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
    put("SUM_AE", abs(float(np.sum(fv)) - float(np.sum(yv))))   # H хоногийн нийлбэрийн алдаа (FR-E2)
    if q_lo is not None and q_hi is not None and not np.all(np.isnan(q_lo)):
        lo, hi = q_lo[mask], q_hi[mask]
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
