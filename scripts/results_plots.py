"""Дипломын Бүлэг 3-ын үр дүнгийн зураг:
  kaggle_wrmsse.png — M5 албан ёсны үнэлгээ (WRMSSE) түвшингээр: систем, Kaggle-ийн 1-р байр, жишиг аргууд
  amazon_backtest.png — Amazon өгөгдөл: системийн жилийн таамаглал ба бодит борлуулалт (2023, 2024)

Хэрэглээ: python scripts/results_plots.py <wrmsse_system.csv> <Scores and Ranks.xlsx> <years_monthly.csv> <out>
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

sysf, scores, monthly, out = sys.argv[1:5]
out = Path(out)
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False, "axes.spines.right": False})

# --- 1. WRMSSE түвшингээр
s = pd.read_csv(sysf, index_col=0)
x = pd.ExcelFile(scores)
b = x.parse("Accuracy-Benchmarks (AL)", header=1).set_index("Unnamed: 0")
t = x.parse("Accuracy-Top50 (AL)", header=1).set_index("Unnamed: 0").iloc[:, :13]
L = [f"L{i}" for i in range(1, 13)]
rows = {
    "Kaggle 1-р байр (LightGBM)": (t.loc["YJ_STU", L].to_numpy(float), "#e8590c", "-"),
    "ES_bu (жишиг)": (b.loc["ES_bu", L].to_numpy(float), "#2b8a3e", "--"),
    "sNaive (жишиг)": (b.loc["sNaive", L].to_numpy(float), "#9aa5b1", ":"),
    "Систем": (s.loc["sys_level", [f"Level{i}" for i in range(1, 13)]].to_numpy(float), "#3a6ea5", "-"),
}
fig, ax = plt.subplots(figsize=(10, 3.8))
for name, (v, c, ls) in rows.items():
    ax.plot(range(1, 13), v, marker="o", ms=4, color=c, ls=ls, lw=2 if name == "Систем" else 1.5, label=name)
ax.set_xticks(range(1, 13))
ax.set_xticklabels(["Нийт", "Муж", "Дэлгүүр", "Ангилал", "Хэлтэс", "Муж×\nангилал", "Муж×\nхэлтэс",
                    "Дэлгүүр×\nангилал", "Дэлгүүр×\nхэлтэс", "Бараа", "Бараа×\nмуж", "Бараа×\nдэлгүүр"], fontsize=8)
ax.set_ylabel("RMSSE (жигнэсэн)")
ax.set_ylim(0, 1.3)
ax.grid(axis="y", alpha=0.3)
ax.legend(frameon=False, fontsize=9, ncol=2, loc="upper left")
fig.tight_layout()
fig.savefig(out / "kaggle_wrmsse.png", dpi=200)

# --- 2. Amazon: сар бүрийн бодит ба системийн таамаглал
m = pd.read_csv(monthly)
cases = [("2023 (2024-файл, 50 бараа)", "2023 он (2022-12 хүртэлх өгөгдлөөр)"),
         ("2024 (2024-файл, 50 бараа)", "2024 он (2023-12 хүртэлх өгөгдлөөр)")]
fig, axes = plt.subplots(1, 2, figsize=(11, 3.6), sharey=True)
for ax, (c, title) in zip(axes, cases):
    d = m[m.case == c]
    lbl = [v[5:] for v in d.month]
    ax.plot(lbl, d.actual, color="#0f1b2d", marker="o", ms=3, label="Бодит борлуулалт")
    ax.plot(lbl, d.system, color="#3a6ea5", lw=2, label="Системийн таамаглал")
    ax.plot(lbl, d.ma3, color="#9aa5b1", ls="--", label="3 сарын дундаж")
    ax.plot(lbl, d.lastyear, color="#e8590c", ls=":", label="Өмнөх өгөгдлийн мөн сар")
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("Сар")
    ax.grid(axis="y", alpha=0.3)
axes[0].set_ylabel("ширхэг / сар")
axes[0].set_ylim(4000, 5200)
axes[1].legend(frameon=False, fontsize=8, loc="lower right")
fig.tight_layout()
fig.savefig(out / "amazon_backtest.png", dpi=200)
print("ok")
