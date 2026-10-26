"""Нэгж тест: хэмжүүрийн томьёо ба тодорхойгүй тохиолдол, эхлэлийн тоо, загвар (§4.9 «Нэгж тест»)."""
import numpy as np
import pandas as pd
import pytest

from fcsys.engine.evaluate import make_splits, metrics_for, origins_for
from fcsys.engine.models import FitContext, make_model, run_series
from fcsys.engine.profile import classify, profile_series
from fcsys.engine.select import select_models


def _m(rows, name):
    return next(r for r in rows if r["metric"] == name)


def test_mase_hand_computed():
    # сургалт: 14 өдөр, m = 7 → |y_t − y_{t−7}| = 2 бүгд → q = 2
    train = np.array([1, 2, 3, 4, 5, 6, 7, 3, 4, 5, 6, 7, 8, 9], dtype=float)
    y = np.array([10, 10, 10], dtype=float)
    f = np.array([12, 9, 10], dtype=float)
    rows = metrics_for(y, f, train, m=7)
    assert _m(rows, "MAE")["value"] == pytest.approx(1.0)
    assert _m(rows, "MASE")["value"] == pytest.approx(0.5)
    assert _m(rows, "Bias")["value"] == pytest.approx(1 / 3)
    assert _m(rows, "WAPE")["value"] == pytest.approx(3 / 30)
    assert _m(rows, "RMSSE")["value"] == pytest.approx(np.sqrt((4 + 1 + 0) / 3 / 4))
    assert _m(rows, "SUM_AE")["value"] == pytest.approx(1.0)


def test_undefined_metrics_have_reason():
    train = np.full(20, 5.0)                       # улирлын зөрүү бүгд 0 → q = 0
    rows = metrics_for(np.zeros(7), np.ones(7), train, m=7)
    mase, wape = _m(rows, "MASE"), _m(rows, "WAPE")
    assert mase["value"] is None and "q = 0" in mase["undefined_reason"]
    assert wape["value"] is None and "Σ|y| = 0" in wape["undefined_reason"]
    short = metrics_for(np.ones(3), np.ones(3), np.ones(5), m=7)
    assert "n ≤ m" in _m(short, "MASE")["undefined_reason"]


def test_excluded_days_dropped_from_pairs():
    y = np.array([1.0, np.nan, 3.0])
    rows = metrics_for(y, np.array([1.0, 100.0, 3.0]), np.arange(30, dtype=float), m=7)
    assert _m(rows, "MAE")["value"] == 0 and _m(rows, "MAE")["n_pairs"] == 2


def test_mase_scale_skips_pairs_with_gap_without_shifting():
    train = np.array([0, 0, 0, 0, 0, 0, 0, 2, np.nan, 2, 2, 2, 2, 2], dtype=float)
    rows = metrics_for(np.array([2.0]), np.array([4.0]), train, m=7)
    assert _m(rows, "MASE")["value"] == pytest.approx(1.0)   # q = 2 (NaN-тай хос алгасагдсан)


def test_origin_counts_match_protocol():
    sp = make_splits(pd.Timestamp("2026-09-30"))
    assert len(origins_for(sp.val_start, sp.val_end)) == 5
    assert len(origins_for(sp.test_start, sp.test_end)) == 9
    for o in origins_for(sp.test_start, sp.test_end):
        assert o + pd.Timedelta(days=30) <= sp.test_end
    assert (sp.test_end - sp.test_start).days == 89 and (sp.val_end - sp.val_start).days == 59


def test_croston_and_sba():
    idx = pd.date_range("2025-01-01", periods=10)
    y = pd.Series([0, 4, 0, 0, 4, 0, 0, 4, 0, 0], index=idx, dtype=float)
    ctx = FitContext(series_id=1, origin=idx[-1], target="sales", horizon=3, seed=1)
    cro, sba = make_model("croston", {"alpha": 0.5}), make_model("sba", {"alpha": 0.5})
    cro.fit(y, ctx)
    sba.fit(y, ctx)
    # z = 4 тогтмол; p: 2 → 2.5 → 2.75 → rate = 4 / 2.75
    assert cro.predict(ctx)["y_hat"].iloc[0] == pytest.approx(4 / 2.75)
    assert sba.predict(ctx)["y_hat"].iloc[0] == pytest.approx(0.75 * 4 / 2.75)


def test_failure_falls_back_and_is_reported():
    idx = pd.date_range("2025-01-01", periods=10)
    y = pd.Series(np.arange(10, dtype=float), index=idx)
    ctx = FitContext(series_id=1, origin=idx[-1], target="sales", horizon=5, seed=1)
    fc, err = run_series(make_model("ets"), y, ctx, make_model("naive"))   # ETS 28 хоног шаардана
    assert err is not None and "богино" in err
    assert (fc["y_hat"] == 9.0).all()


def test_classification_thresholds():
    assert classify(1.0, 0.1) == "smooth" and classify(1.0, 0.9) == "erratic"
    assert classify(2.0, 0.1) == "intermittent" and classify(2.0, 0.9) == "lumpy"
    prof = profile_series(pd.Series([0, 0, 3, 0, 0, 3, 0, 0, 3], dtype=float,
                                    index=pd.date_range("2025-01-01", periods=9)))
    assert prof["adi"] == pytest.approx(3.0) and prof["class"] == "intermittent"


def test_selection_falls_back_to_baseline_when_not_better():
    rows = []
    for sid in (1, 2):
        for o in ("2026-01-01", "2026-01-08"):
            rows += [{"run_id": 10, "series_id": sid, "horizon": 7, "metric": "MASE", "value": 1.0, "origin_date": o},
                     {"run_id": 11, "series_id": sid, "horizon": 7, "metric": "MASE", "value": 1.2, "origin_date": o}]
    metrics = pd.DataFrame(rows)
    runs = pd.DataFrame({"run_id": [10, 11], "label": ["snaive", "ets"]})
    prof = pd.DataFrame({"series_id": [1, 2], "class": ["smooth", "smooth"]})
    sel = select_models(metrics, prof, runs, baseline_run_id=10, level="global")
    assert set(sel["run_id"]) == {10} and "суурь" in sel["rule"].iloc[0]
    metrics.loc[metrics.run_id == 11, "value"] = 0.8
    sel = select_models(metrics, prof, runs, baseline_run_id=10, level="global")
    assert set(sel["run_id"]) == {11}
