"""M5 туршилтын зураг (дипломын Бүлэг 3): загваруудын тестийн WAPE, нэг дэлгүүрийн таамаглалын жишээ."""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

d, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
res = pd.read_csv(d / "m5_results.csv")
ORDER = ["naive", "snaive", "ma", "croston", "sba", "ets", "ets_damped", "sarima", "combo", "selected", "lgbm", "lgbm_ratio"]
NAME = {"ma": "Хөдөлгөөнт дундаж", "naive": "Naive", "snaive": "Улирлын naive", "ets": "ETS", "ets_damped": "ETS (чиг хандлага)",
        "sarima": "SARIMA", "combo": "Хосолсон", "croston": "Croston", "sba": "SBA", "selected": "Системийн сонголт",
        "lgbm": "LightGBM (ширхэг)", "lgbm_ratio": "LightGBM (харьцангуй)"}
LVL = {"store": "Дэлгүүр (10)", "dept_store": "Хэлтэс × дэлгүүр (70)", "item_store": "Бараа × дэлгүүр (1000)"}
fig, axes = plt.subplots(1, 3, figsize=(11, 4.2), sharey=True)
for ax, lvl in zip(axes, LVL):
    r = res[(res.level == lvl) & (res.k == 1)].set_index("model").reindex(ORDER)
    colors = ["#146ef5" if m == "selected" else "#e8590c" if m.startswith("lgbm") else "#9aa5b1" for m in ORDER]
    ax.barh([NAME[m] for m in ORDER], r.WAPE * 100, color=colors)
    for y, v in enumerate(r.WAPE * 100):
        ax.text(v + 0.3, y, f"{v:.1f}", va="center", fontsize=8)
    ax.set_title(LVL[lvl], fontsize=10)
    ax.set_xlabel("WAPE, % (сарын, тест)")
    ax.invert_yaxis()
fig.tight_layout()
fig.savefig(out / "m5_wape.png", dpi=200)

# Жишээ: нийт 10 дэлгүүрийн нийлбэр биш — CA_3 дэлгүүр, тестийн эхний эхлэлээс 12 сар
st = pd.read_parquet(d / "stat_forecasts.parquet")
lg = pd.read_parquet(d / "lgbm_ratio_forecasts.parquet").merge(pd.read_parquet(d / "m5_meta.parquet"), on="id")
mon = pd.read_parquet(d / "m5_monthly.parquet").merge(pd.read_parquet(d / "m5_meta.parquet"), on="id")
store = "CA_3"
act = mon.assign(q=mon.qty.fillna(0)).query("store_id == @store").groupby("month").q.sum()
o = pd.Timestamp("2015-05-01")
fig, ax = plt.subplots(figsize=(10, 3.8))
ax.plot(act.loc["2013-01-01":].index, act.loc["2013-01-01":] / 1000, color="#0f1b2d", lw=1.6, label="Бодит борлуулалт")
for m, c, ls in (("ets", "#146ef5", "-"), ("sarima", "#2b8a3e", "--"), ("ma", "#9aa5b1", ":")):
    f = st[(st.level == "store") & (st.sid == store) & (st.model == m) & (st.origin == o)]
    ax.plot(f.target, f.y_hat / 1000, color=c, ls=ls, lw=1.6, label=NAME[m])
f = lg[(lg.store_id == store) & (lg.origin == o)].groupby("target").y_hat.sum()
ax.plot(f.index, f / 1000, color="#e8590c", lw=1.6, ls="-.", label="LightGBM, харьцангуй (доороос дээш)")
ax.axvline(o + pd.DateOffset(days=15), color="#666", lw=0.8, ls=":")
ax.text(o - pd.DateOffset(days=20), ax.get_ylim()[0] + 0.03 * (ax.get_ylim()[1] - ax.get_ylim()[0]), "эхлэл 2015.05", fontsize=8, ha="right")
ax.set_ylabel("мянган ширхэг / сар")
ax.legend(fontsize=8, ncol=3, loc="lower left", frameon=False)
fig.tight_layout()
fig.savefig(out / "m5_store_example.png", dpi=200)
print("ok")
