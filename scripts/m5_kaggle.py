"""Системийг Kaggle M5 Forecasting – Accuracy тэмцээний албан ёсны үнэлгээгээр (WRMSSE, 12 түвшин,
2016-05-23 … 2016-06-19, 28 өдөр) шалгана.

Тэмцээнд оролцогчид 2016-05-22 хүртэлх өгөгдлөөр бараа×дэлгүүрийн өдрийн таамаглал илгээж, дээд түвшнийг
доороос нэмж (bottom-up) үнэлүүлсэн. Систем зөвхөн бүтэн сарын өгөгдөл ашигладаг тул 2016-04 хүртэлх
өгөгдлөөр 5, 6-р сарыг таамаглаж, сарын дүнг өдөрт хуваана.

Хувилбарууд (бүгд bottom-up, бараа×дэлгүүрийн 30 490 цуваа):
  naive, snaive        — тэмцээний жишиг аргууд (WRMSSE-ийн тооцоог албан ёсны тоотой тулгаж шалгана)
  sys_flat             — системийн сонголт (бараа түвшинд «өнгөрсөн сар»), сарын дүнг өдөрт тэнцүү хуваасан
  sys_dow              — дээрх, сарын дүнг долоо хоногийн өдрийн жингээр (2016-04-ийн сүүлийн 8 долоо хоног) хуваасан
  sys_level            — L1–L9-ийг тухайн түвшний цуваанд системийн «хосолсон» аргаар шууд таамагласан,
                         L10–L12-т sys_dow (албан ёсны bottom-up шаардлагыг хангахгүй, тайлбарын зорилгоор)

Хэрэглээ: python scripts/m5_kaggle.py --raw /tmp/m5/x --out /tmp/m5/kaggle
"""
import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fcsys.engine.models import FitContext, make_model, run_series  # noqa: E402

H = 28
FIRST_TEST = 1942                       # d_1942 = 2016-05-23
ORIGIN = pd.Timestamp("2016-04-01")     # системийн сүүлийн бүтэн сар
LEVELS = {                              # түвшин: (бүлэглэх баганууд), weights файлын Agg_Level_1/2
    "Level1": [], "Level2": ["state_id"], "Level3": ["store_id"], "Level4": ["cat_id"], "Level5": ["dept_id"],
    "Level6": ["state_id", "cat_id"], "Level7": ["state_id", "dept_id"], "Level8": ["store_id", "cat_id"],
    "Level9": ["store_id", "dept_id"], "Level10": ["item_id"], "Level11": ["state_id", "item_id"],
    "Level12": ["item_id", "store_id"],
}
KEYS = ["item_id", "dept_id", "cat_id", "store_id", "state_id"]


def key(df, cols):
    if not cols:
        return pd.Series("Total", index=df.index), pd.Series("X", index=df.index)
    a = df[cols[0]]
    b = df[cols[1]] if len(cols) > 1 else pd.Series("X", index=df.index)
    return a, b


def aggregate(meta, mat, cols):
    a, b = key(meta, cols)
    g = pd.DataFrame(mat).groupby([a.values, b.values]).sum()
    g.index.names = ["Agg_Level_1", "Agg_Level_2"]
    return g


def scale_of(train):
    """RMSSE хуваарь: эхний борлуулалтаас хойших өдрийн зөрүүний квадратын дундаж (тэмцээний тодорхойлолт)."""
    t = train.to_numpy(float)
    started = np.maximum.accumulate(t > 0, axis=1)
    d = np.diff(t, axis=1) ** 2
    mask = started[:, 1:]
    return (d * mask).sum(1) / np.maximum(mask.sum(1), 1)


def wrmsse(meta, train, test, fc, weights):
    out = {}
    for lv, cols in LEVELS.items():
        tr, te, f = (aggregate(meta, m, cols) for m in (train, test, fc))
        sc = scale_of(tr)
        rmsse = np.sqrt(((te.to_numpy() - f.loc[te.index].to_numpy()) ** 2).mean(1) / sc)
        w = weights[weights.Level_id == lv].set_index(["Agg_Level_1", "Agg_Level_2"]).weight.reindex(te.index)
        assert w.notna().all(), lv
        out[lv] = float((w.to_numpy() * rmsse).sum())
    out["Avg"] = float(np.mean([out[k] for k in LEVELS]))
    return out


def month_to_days(month_fc, days, profile=None):
    """Сарын таамаглалыг (May, June) өдөрт хуваана. profile: (n, 7) долоо хоногийн өдрийн жин."""
    n = len(month_fc)
    res = np.zeros((n, len(days)))
    for j, d in enumerate(days):
        mi = 0 if d.month == 5 else 1
        dim = d.days_in_month
        if profile is None:
            res[:, j] = month_fc[:, mi] / dim
        else:
            # сарын дотор тухайн гарагийн жинг нормчилно: сарын нийлбэр = сарын таамаглал
            mdays = pd.date_range(d.replace(day=1), periods=dim, freq="D")
            denom = profile[:, mdays.dayofweek].sum(1)
            res[:, j] = month_fc[:, mi] * profile[:, d.dayofweek] / np.where(denom > 0, denom, np.nan)
            res[:, j] = np.where(denom > 0, res[:, j], month_fc[:, mi] / dim)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    raw, out = Path(a.raw), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    warnings.simplefilter("ignore")

    tr = pd.read_csv(raw / "sales_train_evaluation.csv")
    te = pd.read_csv(raw / "sales_test_evaluation.csv")
    cal = pd.read_csv(raw / "calendar.csv", parse_dates=["date"])
    weights = pd.read_csv(raw / "weights_evaluation.csv")
    assert (tr[KEYS].values == te[KEYS].values).all()
    meta = tr[KEYS].reset_index(drop=True)
    dcols = [c for c in tr.columns if c.startswith("d_")]
    train = tr[dcols].astype(np.float32)
    test = te[[f"d_{i}" for i in range(FIRST_TEST, FIRST_TEST + H)]].to_numpy(np.float64)
    if "d" not in cal.columns:                       # зарим хувилбарт «d» багана байхгүй: d_1 = 2011-01-29
        cal["d"] = [f"d_{i + 1}" for i in range(len(cal))]
    dates = cal.set_index("d").date
    tdates = pd.DatetimeIndex(dates.loc[dcols].values)
    fdays = pd.DatetimeIndex(dates.loc[[f"d_{i}" for i in range(FIRST_TEST, FIRST_TEST + H)]].values)
    T = train.to_numpy(np.float64)

    fc = {}
    fc["naive"] = np.repeat(T[:, -1:], H, axis=1)
    fc["snaive"] = np.tile(T[:, -7:], (1, 4))

    # системийн бараа түвшний сонголт: «өнгөрсөн сар» (naive), 2016-04-ийн нийлбэр → 5, 6-р сар
    apr = (tdates >= "2016-04-01") & (tdates <= "2016-04-30")
    month_fc = np.repeat(T[:, apr].sum(1, keepdims=True), 2, axis=1)
    fc["sys_flat"] = month_to_days(month_fc, fdays)
    last8 = (tdates <= "2016-04-30") & (tdates > pd.Timestamp("2016-04-30") - pd.Timedelta(days=56))
    prof = np.zeros((len(T), 7))
    for dw in range(7):
        prof[:, dw] = T[:, last8 & (tdates.dayofweek == dw)].sum(1)
    fc["sys_dow"] = month_to_days(month_fc, fdays, prof)

    res = {k: wrmsse(meta, train, test, v, weights) for k, v in fc.items()}

    # L1–L9: түвшний цуваанд системийн хосолсон арга (ETS, ETS+trend, SARIMA) — сарын түвшинд
    mon_idx = pd.PeriodIndex(tdates, freq="M")
    full = (mon_idx >= pd.Period("2011-02", "M")) & (mon_idx <= pd.Period("2016-04", "M"))
    lvl = {}
    fb = make_model("ma", {"window": 3})
    for lv in [f"Level{i}" for i in range(1, 10)]:
        g = aggregate(meta, T, LEVELS[lv])
        gm = pd.DataFrame(g.to_numpy()[:, full], index=g.index).T.groupby(mon_idx[full]).sum().T
        gm.columns = gm.columns.to_timestamp()
        dprof = np.zeros((len(g), 7))
        G = g.to_numpy()
        for dw in range(7):
            dprof[:, dw] = G[:, last8 & (tdates.dayofweek == dw)].sum(1)
        mfc = np.zeros((len(g), 2))
        for i, (_, y) in enumerate(gm.iterrows()):
            ctx = FitContext(series_id=0, origin=ORIGIN, target="sales", horizon=12, seed=1)
            ps = []
            for m, p in (("ets", {"seasonal": "add"}), ("ets", {"seasonal": "add", "trend": "add", "damped": True}),
                         ("sarima", {"order": [1, 1, 1], "seasonal_order": [0, 1, 1]})):
                f, _ = run_series(make_model(m, p), y.astype(float), ctx, fb)
                ps.append(f["y_hat"].to_numpy()[:2])
            mfc[i] = np.mean(ps, axis=0)
        dfc = month_to_days(mfc, fdays, dprof)
        tr_l, te_l = g, aggregate(meta, test, LEVELS[lv])
        sc = scale_of(tr_l)
        rmsse = np.sqrt(((te_l.to_numpy() - dfc) ** 2).mean(1) / sc)
        w = weights[weights.Level_id == lv].set_index(["Agg_Level_1", "Agg_Level_2"]).weight.reindex(te_l.index)
        lvl[lv] = float((w.to_numpy() * rmsse).sum())
    sl = {**lvl, **{k: res["sys_dow"][k] for k in ("Level10", "Level11", "Level12")}}
    sl["Avg"] = float(np.mean([sl[k] for k in LEVELS]))
    res["sys_level"] = sl

    df = pd.DataFrame(res).T[list(LEVELS) + ["Avg"]]
    df.to_csv(out / "wrmsse_system.csv")

    # 28 хоногийн нийт дүнгийн алдаа (WAPE), түвшингээр — сарын төлөвлөлтөд ойр хэмжүүр
    rows = []
    for name, f in fc.items():
        for lv in ("Level1", "Level3", "Level9", "Level12"):
            t28 = aggregate(meta, test, LEVELS[lv]).sum(1)
            f28 = aggregate(meta, f, LEVELS[lv]).sum(1)
            rows.append({"variant": name, "level": lv, "wape_28d_total": float((t28 - f28).abs().sum() / t28.sum()),
                         "bias": float(f28.sum() / t28.sum() - 1)})
    pd.DataFrame(rows).to_csv(out / "total28.csv", index=False)
    pd.set_option("display.width", 250)
    print(df.round(3).to_string())
    print(pd.DataFrame(rows).round(3).to_string())


if __name__ == "__main__":
    main()
