"""models — нэгдсэн интерфейстэй загварууд (FR-M1, Z7, §4.4 «Загварын интерфейс»).

Энэ хувилбарт: naive, seasonal naive (m = 7), ETS, Croston, SBA.
SARIMA, Prophet, XGBoost (recursive) дараагийн үе шатанд ижил интерфейсээр нэмэгдэнэ.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .features import fill_for_model


@dataclass(frozen=True)
class FitContext:
    series_id: int
    origin: pd.Timestamp          # сүүлийн мэдэгдэх өдөр o
    target: str                   # 'sales' | 'demand'
    horizon: int                  # H, 30 хүртэл
    seed: int
    calendar: pd.DataFrame | None = None     # ирээдүйд мэдэгдэх календарь
    known_price: pd.DataFrame | None = None  # known_at ≤ origin мөрүүд


class Forecaster:
    name: str = "base"
    feature_set: str = "none"
    has_interval: bool = False

    def __init__(self, **params):
        self.params = params

    def fit(self, history: pd.Series, ctx: FitContext) -> None:
        """history: зөвхөн day ≤ ctx.origin мөр (NaN = зорилтоос хасагдсан өдөр)."""
        raise NotImplementedError

    def predict(self, ctx: FitContext) -> pd.DataFrame:
        """Багана: h, target_date, y_hat, q_lo, q_hi (интервалгүй бол NaN)."""
        raise NotImplementedError

    def _frame(self, ctx: FitContext, y_hat, q_lo=None, q_hi=None) -> pd.DataFrame:
        h = np.arange(1, ctx.horizon + 1)
        y_hat = np.clip(np.asarray(y_hat, dtype=float), 0, None)  # борлуулалт сөрөг байхгүй
        if not np.all(np.isfinite(y_hat)):
            raise ValueError(f"{self.name}: таамаглалд төгсгөлгүй утга гарсан")
        df = pd.DataFrame({"h": h, "target_date": ctx.origin + pd.to_timedelta(h, unit="D"),
                           "y_hat": y_hat})
        df["q_lo"] = np.clip(q_lo, 0, None) if q_lo is not None else np.nan
        df["q_hi"] = np.clip(q_hi, 0, None) if q_hi is not None else np.nan
        return df


def _check_history(history: pd.Series, ctx: FitContext, min_len: int = 1) -> pd.Series:
    if len(history) and history.index.max() > ctx.origin:
        raise AssertionError("Мэдээллийн алдагдал: түүхэнд эхлэлээс хойших өдөр байна")
    y = fill_for_model(history)
    if len(y) < min_len:
        raise ValueError(f"Түүх хэт богино ({len(y)} < {min_len})")
    return y


class Naive(Forecaster):
    name = "naive"

    def fit(self, history, ctx):
        self._last = float(_check_history(history, ctx).iloc[-1])

    def predict(self, ctx):
        return self._frame(ctx, np.full(ctx.horizon, self._last))


class SeasonalNaive(Forecaster):
    name = "snaive"

    def fit(self, history, ctx):
        m = int(self.params.get("m", 7))
        y = _check_history(history, ctx, min_len=m)
        self._season = y.values[-m:]
        self._m = m

    def predict(self, ctx):
        reps = int(np.ceil(ctx.horizon / self._m))
        return self._frame(ctx, np.tile(self._season, reps)[: ctx.horizon])


class ETS(Forecaster):
    """statsmodels ETSModel; анхдагч: нэмэх алдаа, долоо хоногийн нэмэх улирал, трендгүй.
    80%-ийн таамаглалын интервал (q = 0.1, 0.9) гаргана (FR-E4)."""
    name = "ets"
    has_interval = True

    def fit(self, history, ctx):
        from statsmodels.tsa.exponential_smoothing.ets import ETSModel
        y = _check_history(history, ctx, min_len=28)
        y = y.asfreq("D")
        trend = self.params.get("trend")            # None | 'add'
        damped = bool(self.params.get("damped", False)) and trend is not None
        seasonal = self.params.get("seasonal", "add")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = ETSModel(y, error="add", trend=trend, damped_trend=damped,
                             seasonal=seasonal, seasonal_periods=7 if seasonal else None)
            self._res = model.fit(disp=False, maxiter=200)

    def predict(self, ctx):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            start = ctx.origin + pd.Timedelta(days=1)
            end = ctx.origin + pd.Timedelta(days=ctx.horizon)
            pred = self._res.get_prediction(start=start, end=end)
            sf = pred.summary_frame(alpha=0.2)
        return self._frame(ctx, sf["mean"].values, sf["pi_lower"].values, sf["pi_upper"].values)


class Croston(Forecaster):
    """Croston (1972): эерэг эрэлтийн хэмжээ z ба завсар p-г тусад нь экспоненциал тэгшитгэнэ."""
    name = "croston"
    _bias = 1.0

    def fit(self, history, ctx):
        alpha = float(self.params.get("alpha", 0.1))
        y = _check_history(history, ctx).values
        nz = np.flatnonzero(y > 0)
        if len(nz) == 0:
            self._rate = 0.0
            return
        z = y[nz[0]]
        p = float(nz[0] + 1)
        last = nz[0]
        for i in nz[1:]:
            interval = i - last
            z = z + alpha * (y[i] - z)
            p = p + alpha * (interval - p)
            last = i
        self._rate = self._bias * z / p

    def predict(self, ctx):
        return self._frame(ctx, np.full(ctx.horizon, self._rate))


class SBA(Croston):
    """Syntetos–Boylan approximation: Croston-ийн хазайлтыг (1 − α/2)-оор засна."""
    name = "sba"

    def fit(self, history, ctx):
        self._bias = 1 - float(self.params.get("alpha", 0.1)) / 2
        super().fit(history, ctx)


MODEL_REGISTRY: dict[str, type[Forecaster]] = {
    m.name: m for m in (Naive, SeasonalNaive, ETS, Croston, SBA)
}
PLANNED_MODELS = ["sarima", "prophet", "xgboost"]


def make_model(name: str, params: dict | None = None) -> Forecaster:
    if name not in MODEL_REGISTRY:
        raise KeyError(f"Загвар '{name}' бүртгэгдээгүй. Боломжтой: {sorted(MODEL_REGISTRY)}")
    return MODEL_REGISTRY[name](**(params or {}))


def run_series(model: Forecaster, history: pd.Series, ctx: FitContext,
               fallback: Forecaster) -> tuple[pd.DataFrame, str | None]:
    """§4.4: бүтэлгүйтлийг нууцлахгүй — fallback ажиллаж, шалтгаан буцна (run_failure-д бичигдэнэ)."""
    past = history.loc[:ctx.origin]
    try:
        model.fit(past, ctx)
        return model.predict(ctx), None
    except AssertionError:
        raise                              # алдагдлыг fallback-аар далдлахгүй
    except Exception as exc:               # noqa: BLE001
        fallback.fit(past, ctx)
        return fallback.predict(ctx), f"{type(exc).__name__}: {exc}"[:500]
