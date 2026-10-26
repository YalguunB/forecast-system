"""Дахин ажиллуулах (NFR-1, §4.9): ижил оролт, тохиргоо, seed → ижил таамаглал; seed нь
багцын хуваалтаас үл хамаарна."""
import numpy as np
import pandas as pd

from fcsys.engine.models import MODEL_REGISTRY, FitContext, make_model
from fcsys.engine.protocol import canonical_hash, derive_seed, normalize_protocol


def _series():
    rng = np.random.default_rng(3)
    idx = pd.date_range("2025-01-01", periods=200)
    y = pd.Series(rng.poisson(5 + 3 * np.sin(np.arange(200) * 2 * np.pi / 7)), index=idx, dtype=float)
    y.iloc[[20, 21, 90]] = np.nan          # хаалттай/дутуу өдөр
    return y


def test_same_input_same_forecast_for_every_model():
    y = _series()
    ctx = FitContext(series_id=42, origin=y.index[169], target="sales", horizon=30, seed=derive_seed(1, 42))
    for name in MODEL_REGISTRY:
        a, b = make_model(name), make_model(name)
        a.fit(y.loc[:ctx.origin], ctx)
        b.fit(y.loc[:ctx.origin], ctx)
        pd.testing.assert_frame_equal(a.predict(ctx), b.predict(ctx))


def test_seed_independent_of_batching_and_protocol_hash_stable():
    assert derive_seed(20261025, 7) == derive_seed(20261025, 7) != derive_seed(20261025, 8)
    p1 = normalize_protocol({"sample": {"max_series": 5}})
    p2 = normalize_protocol({"sample": {"max_series": 5}})
    assert canonical_hash(p1) == canonical_hash(p2)
    assert canonical_hash(p1) != canonical_hash(normalize_protocol({"sample": {"max_series": 6}}))
