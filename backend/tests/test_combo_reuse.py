"""Хосолсон арга: бүрэлдэхүүний хадгалсан таамаглалаас дундаж авах нь шууд тааруулсантай ижил байх ёстой."""
import numpy as np
import pandas as pd

from fcsys.engine.jobs import _combo_from_members
from fcsys.engine.models import Combination, FitContext, make_model, run_series


def _series(seed: int) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2019-01-01", periods=60, freq="MS")
    season = 20 * np.sin(2 * np.pi * np.arange(60) / 12)
    return pd.Series(np.clip(100 + np.arange(60) * 0.8 + season + rng.normal(0, 8, 60), 0, None), index=idx)


def _cache_from_members(y, sid, origins, fail_member=None):
    """forecast_value / run_failure хүснэгтэд хадгалагдах хэлбэрийг дуурайна."""
    runs = [10, 11, 12]
    vals, failed = {}, set()
    for rid, spec in zip(runs, Combination.DEFAULT_MEMBERS):
        for o in origins:
            ctx = FitContext(series_id=sid, origin=o, target="sales", horizon=12, seed=1)
            fc, err = run_series(make_model(spec["name"], spec["params"]), y, ctx, make_model("ma", {"window": 3}))
            if err or rid == fail_member:
                failed.add((rid, sid, o.date()))
            vals[(rid, sid, o.date())] = [{"h": int(r.h), "y_hat": r.y_hat, "q_lo": None if np.isnan(r.q_lo) else r.q_lo,
                                            "q_hi": None if np.isnan(r.q_hi) else r.q_hi} for r in fc.itertuples()]
    return {"runs": runs, "vals": vals, "failed": failed}


def test_combo_from_stored_members_equals_direct_fit():
    y = _series(3)
    origins = [pd.Timestamp("2022-06-01"), pd.Timestamp("2023-01-01")]
    cache = _cache_from_members(y, 7, origins)
    for o in origins:
        ctx = FitContext(series_id=7, origin=o, target="sales", horizon=12, seed=1)
        direct, err = run_series(make_model("combo"), y, ctx, make_model("ma", {"window": 3}))
        assert err is None
        reused = _combo_from_members(cache, make_model("combo"), 7, ctx)
        for c in ("y_hat", "q_lo", "q_hi"):
            np.testing.assert_allclose(reused[c].values, direct[c].values, rtol=1e-12, atol=1e-9)


def test_combo_reuse_skips_failed_member_and_waits_for_missing():
    y = _series(5)
    o = pd.Timestamp("2022-06-01")
    ctx = FitContext(series_id=7, origin=o, target="sales", horizon=12, seed=1)
    cache = _cache_from_members(y, 7, [o], fail_member=12)          # SARIMA бүтэлгүйтсэн гэж үзье
    reused = _combo_from_members(cache, make_model("combo"), 7, ctx)
    two = np.mean([np.array([r["y_hat"] for r in cache["vals"][(rid, 7, o.date())]]) for rid in (10, 11)], axis=0)
    np.testing.assert_allclose(reused["y_hat"].values, np.clip(two, 0, None))
    del cache["vals"][(11, 7, o.date())]                             # бүрэлдэхүүн хараахан тооцогдоогүй
    assert _combo_from_members(cache, make_model("combo"), 7, ctx) is None
