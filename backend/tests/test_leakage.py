"""Мэдээллийн алдагдлын тест (§4.9, FR-S4, NFR-8, Z3).

Эхлэл o-ийн дараах бодит утгыг өөрчилсөн өгөгдөл дээр o дахь шинж ба детерминист
загварын таамаглал өөрчлөгдөхгүй байх ёстой. Hypothesis санамсаргүй цуваа, эхлэл,
өөрчлөлт үүсгэнэ.
"""
import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from fcsys.engine.features import build_features, known_prices
from fcsys.engine.models import MODEL_REGISTRY, FitContext, make_model

N = 120
IDX = pd.date_range("2025-01-01", periods=N)


@st.composite
def series_and_origin(draw):
    vals = draw(st.lists(st.one_of(st.floats(0, 50, allow_nan=False), st.just(float("nan"))),
                         min_size=N, max_size=N))
    vals[0] = 1.0
    origin_i = draw(st.integers(40, N - 31))
    future = draw(st.lists(st.floats(0, 1000, allow_nan=False), min_size=N - origin_i - 1,
                           max_size=N - origin_i - 1))
    return pd.Series(vals, index=IDX), origin_i, future


def _perturb(y, origin_i, future):
    y2 = y.copy()
    y2.iloc[origin_i + 1:] = future
    return y2


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(series_and_origin())
def test_features_ignore_values_after_origin(data):
    y, oi, future = data
    o = IDX[oi]
    prices = pd.DataFrame({"date": [IDX[10], IDX[oi + 5]], "price": [100.0, 999.0],
                           "price_kind": ["actual", "actual"], "known_at": [IDX[10], IDX[oi + 5]]})
    a = build_features(y, o, 30, prices=prices)
    b = build_features(_perturb(y, oi, future), o, 30, prices=prices)
    pd.testing.assert_frame_equal(a, b)
    assert (a["price_approved"] == 100.0).all()          # ирээдүйн бодит үнэ орохгүй (DQ-10)


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(series_and_origin(), st.sampled_from(sorted(MODEL_REGISTRY)))
def test_model_forecast_ignores_values_after_origin(data, model_name):
    y, oi, future = data
    o = IDX[oi]
    ctx = FitContext(series_id=1, origin=o, target="sales", horizon=30, seed=1)
    outs = []
    for series in (y, _perturb(y, oi, future)):
        m = make_model(model_name)
        try:
            m.fit(series.loc[:o], ctx)
            outs.append(m.predict(ctx)["y_hat"].values)
        except ValueError:
            outs.append("error")
    if isinstance(outs[0], str) or isinstance(outs[1], str):
        assert outs[0] == outs[1]
    else:
        np.testing.assert_allclose(outs[0], outs[1])


def test_model_refuses_history_after_origin():
    y = pd.Series(np.ones(60), index=pd.date_range("2025-01-01", periods=60))
    ctx = FitContext(series_id=1, origin=y.index[30], target="sales", horizon=7, seed=1)
    with pytest.raises(AssertionError, match="алдагдал"):
        make_model("naive").fit(y, ctx)


def test_known_prices_respects_known_at():
    p = pd.DataFrame({"date": pd.to_datetime(["2025-01-01", "2025-03-01", "2025-03-01"]),
                      "price": [1.0, 2.0, 3.0], "price_kind": ["actual", "approved_plan", "scenario"],
                      "known_at": pd.to_datetime(["2025-01-01", "2025-02-20", "2025-01-01"])})
    assert list(known_prices(p, pd.Timestamp("2025-02-10"))["price"]) == [1.0]
    assert list(known_prices(p, pd.Timestamp("2025-02-25"))["price"]) == [1.0, 2.0]
