"""models — нэгдсэн интерфейстэй сарын загварууд (FR-M1, Z7, §4.4 «Загварын интерфейс»).

Энэ хувилбарт: гулсах дундаж (суурь загвар), naive, улирлын naive (m = 12), ETS (үндсэн загвар),
SARIMA, Croston, SBA. Prophet, XGBoost дараагийн үе шатанд ижил интерфейсээр нэмэгдэнэ.
Цуваа нь сарын эхлэлээр индекслэгдсэн (MS); эхлэл o = мэдэгдэх сүүлийн сар; h = 1..H сар.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .features import fill_for_model

SEASON = 12


@dataclass(frozen=True)
class FitContext:
    series_id: int
    origin: pd.Timestamp          # мэдэгдэх сүүлийн сар o (сарын эхлэл)
    target: str                   # 'sales' | 'demand'
    horizon: int                  # H, 12 хүртэл сар
    seed: int
    calendar: pd.DataFrame | None = None
    known_price: pd.DataFrame | None = None


def target_months(origin: pd.Timestamp, horizon: int) -> pd.DatetimeIndex:
    return pd.date_range(pd.Timestamp(origin) + pd.DateOffset(months=1), periods=horizon, freq="MS")


class Forecaster:
    name: str = "base"
    feature_set: str = "none"
    has_interval: bool = False

    def __init__(self, **params):
        self.params = params

    def fit(self, history: pd.Series, ctx: FitContext) -> None:
        """history: зөвхөн сар ≤ ctx.origin мөр (NaN = тодорхойгүй сар)."""
        raise NotImplementedError

    def predict(self, ctx: FitContext) -> pd.DataFrame:
        """Багана: h, target_date (зорилтот сарын эхлэл), y_hat, q_lo, q_hi (интервалгүй бол NaN)."""
        raise NotImplementedError

    def _frame(self, ctx: FitContext, y_hat, q_lo=None, q_hi=None) -> pd.DataFrame:
        h = np.arange(1, ctx.horizon + 1)
        y_hat = np.clip(np.asarray(y_hat, dtype=float), 0, None)  # борлуулалт сөрөг байхгүй
        if not np.all(np.isfinite(y_hat)):
            raise ValueError(f"{self.name}: таамаглалд төгсгөлгүй утга гарсан")
        df = pd.DataFrame({"h": h, "target_date": target_months(ctx.origin, ctx.horizon), "y_hat": y_hat})
        df["q_lo"] = np.clip(q_lo, 0, None) if q_lo is not None else np.nan
        df["q_hi"] = np.clip(q_hi, 0, None) if q_hi is not None else np.nan
        if q_lo is not None:
            df["q_lo"] = np.minimum(df["q_lo"], df["y_hat"])
            df["q_hi"] = np.maximum(df["q_hi"], df["y_hat"])
        return df


def _check_history(history: pd.Series, ctx: FitContext, min_len: int = 1) -> pd.Series:
    if len(history) and history.index.max() > ctx.origin:
        raise AssertionError("Мэдээллийн алдагдал: түүхэнд эхлэлээс хойших сар байна")
    y = fill_for_model(history, period=SEASON)
    if len(y) < min_len:
        raise ValueError(f"Түүх хэт богино ({len(y)} сар < {min_len})")
    return y


class MovingAverage(Forecaster):
    """Гулсах дундаж (дипломын суурь загвар): сүүлийн window сарын дундаж."""
    name = "ma"

    def fit(self, history, ctx):
        w = int(self.params.get("window", 3))
        y = _check_history(history, ctx, min_len=1)
        self._level = float(y.values[-w:].mean())

    def predict(self, ctx):
        return self._frame(ctx, np.full(ctx.horizon, self._level))


class Naive(Forecaster):
    name = "naive"

    def fit(self, history, ctx):
        self._last = float(_check_history(history, ctx).iloc[-1])

    def predict(self, ctx):
        return self._frame(ctx, np.full(ctx.horizon, self._last))


class SeasonalNaive(Forecaster):
    """Өнгөрсөн жилийн ижил сарын утга (m = 12)."""
    name = "snaive"

    def fit(self, history, ctx):
        m = int(self.params.get("m", SEASON))
        y = _check_history(history, ctx, min_len=m)
        self._season = y.values[-m:]
        self._m = m

    def predict(self, ctx):
        reps = int(np.ceil(ctx.horizon / self._m))
        return self._frame(ctx, np.tile(self._season, reps)[: ctx.horizon])


class ETS(Forecaster):
    """statsmodels ETSModel (дипломын үндсэн загвар): нэмэх алдаа; улирал (m = 12) нь 24-өөс
    доошгүй сарын түүхтэй үед л; тренд сонголттой (damped). 80%-ийн интервал (q = 0.1, 0.9)."""
    name = "ets"
    has_interval = True

    def fit(self, history, ctx):
        from statsmodels.tsa.exponential_smoothing.ets import ETSModel
        y = _check_history(history, ctx, min_len=8).asfreq("MS")
        trend = self.params.get("trend")            # None | 'add'
        damped = bool(self.params.get("damped", False)) and trend is not None
        seasonal = self.params.get("seasonal", "add") if len(y) >= 2 * SEASON else None
        self.used_seasonal = seasonal
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = ETSModel(y, error="add", trend=trend, damped_trend=damped,
                             seasonal=seasonal, seasonal_periods=SEASON if seasonal else None)
            self._res = model.fit(disp=False, maxiter=200)

    def predict(self, ctx):
        idx = target_months(ctx.origin, ctx.horizon)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pred = self._res.get_prediction(start=idx[0], end=idx[-1])
            sf = pred.summary_frame(alpha=0.2)
        return self._frame(ctx, sf["mean"].values, sf["pi_lower"].values, sf["pi_upper"].values)


class SARIMA(Forecaster):
    """statsmodels SARIMAX: (p,d,q)(P,D,Q,12). Улирлын хэсэг 36-аас доошгүй сарын түүхтэй үед л."""
    name = "sarima"
    has_interval = True

    def fit(self, history, ctx):
        from statsmodels.tsa.statespace.sarimax import SARIMAX
        y = _check_history(history, ctx, min_len=12).asfreq("MS")
        order = tuple(self.params.get("order", (1, 1, 1)))
        seasonal = tuple(self.params.get("seasonal_order", (0, 1, 1))) if len(y) >= 3 * SEASON else (0, 0, 0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._res = SARIMAX(y, order=order, seasonal_order=(*seasonal, SEASON if any(seasonal) else 0),
                                enforce_stationarity=False, enforce_invertibility=False).fit(disp=False, maxiter=100)

    def predict(self, ctx):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            f = self._res.get_forecast(steps=ctx.horizon)
            ci = f.conf_int(alpha=0.2)
        return self._frame(ctx, f.predicted_mean.values, ci.iloc[:, 0].values, ci.iloc[:, 1].values)


class Croston(Forecaster):
    """Croston (1972): эерэг борлуулалтын хэмжээ z ба завсар p-г тусад нь экспоненциал тэгшитгэнэ.
    Борлуулалтгүй сар олонтой (тасалдсан) цуваанд."""
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
    m.name: m for m in (MovingAverage, Naive, SeasonalNaive, ETS, SARIMA, Croston, SBA)
}
PLANNED_MODELS = ["prophet", "xgboost"]


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
