"""Эрэлтийн (D) таамаглалыг шалгах синтетик өгөгдөл — ЖИНХЭНЭ эрэлт мэдэгдэж байна.

Бодит өгөгдөлд нөөц дууссан өдрийн эрэлт хэзээ ч харагддаггүй тул «систем эрэлтийг зөв таамагласан уу»
гэдгийг зөвхөн жинхэнэ эрэлтийг мэдэж байгаа синтетик өгөгдлөөр шалгана.

Загвар (бараа бүр, нэг салбар B01, өдөр бүр):
  эрэлт   d_t ~ Poisson(λ_t),  λ_t = суурь × тренд × жилийн улирал × 7 хоногийн хэлбэлзэл
  нөөц    (s, S) бодлого: үлдэгдэл + замд байгаа ≤ s бол S хүртэл захиална, L хоногийн дараа ирнэ
  борлуулалт = min(d_t, өглөөний үлдэгдэл)  → нөөц дуусахад эрэлт «халхлагдана» (censored)
Бараануудын хагас нь «хатуу» бодлоготой (s жижиг) → нөөц байнга тасарна; нөгөө хагас нь бараг тасрахгүй.

Гаралт:
  transactions.csv  — системд өгөх борлуулалт (өдөр × бараа)
  inventory.csv     — өглөөний үлдэгдэл, available = үлдэгдэл > 0 (найдвартай)
  true_demand.csv   — ЖИНХЭНЭ эрэлт ба борлуулалт (системд ӨГӨХГҮЙ, зөвхөн шалгалтад)

Хэрэглээ: python scripts/gen_demand_test.py --out data/demand_test --seed 7
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/demand_test")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--products", type=int, default=24)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    days = pd.date_range(a.start, a.end, freq="D")
    n = len(days)
    doy = days.dayofyear.values

    tx, inv, truth = [], [], []
    for k in range(a.products):
        pid = f"D{k + 1:03d}"
        tight = k % 2 == 0                                   # хагас нь байнга нөөц тасардаг
        base = rng.uniform(4, 20)
        amp = rng.uniform(0.15, 0.35)                        # жилийн улирлын далайц
        peak = rng.uniform(0, 365)
        trend = np.linspace(1.0, 1.0 + rng.uniform(-0.15, 0.3), n)
        week = 1 + rng.uniform(0.05, 0.25) * np.sin(2 * np.pi * (days.dayofweek.values - rng.integers(7)) / 7)
        lam = base * trend * week * (1 + amp * np.cos(2 * np.pi * (doy - peak) / 365.25))
        demand = rng.poisson(lam)

        lead = int(rng.integers(4, 11))
        mean_d = float(lam.mean())
        s_lvl = mean_d * lead * (rng.uniform(0.45, 0.75) if tight else 1.6)
        S_lvl = s_lvl + mean_d * rng.uniform(10, 20)
        on_hand, pipeline = S_lvl, []                        # pipeline: (ирэх өдрийн индекс, тоо)
        for i in range(n):
            on_hand += sum(q for t, q in pipeline if t == i)
            pipeline = [(t, q) for t, q in pipeline if t > i]
            morning = int(round(on_hand))
            sold = int(min(demand[i], morning))
            on_hand = morning - sold
            if on_hand + sum(q for _, q in pipeline) <= s_lvl:
                pipeline.append((i + lead, int(round(S_lvl - on_hand - sum(q for _, q in pipeline)))))
            d = days[i].strftime("%Y-%m-%d")
            inv.append((d, pid, "B01", morning, int(morning > 0), "reliable"))
            truth.append((d, pid, int(demand[i]), sold, int(morning == 0), "tight" if tight else "normal"))
            if sold > 0:
                tx.append((f"R{len(tx) + 1:08d}", d, pid, "B01", sold, "ширхэг", sold * 1000, 0))

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(tx, columns=["receipt_no", "sale_date", "item", "store", "quantity", "uom", "revenue", "is_return"]) \
        .to_csv(out / "transactions.csv", index=False)
    pd.DataFrame(inv, columns=["date", "product_id", "branch_id", "on_hand", "available", "reliability"]) \
        .to_csv(out / "inventory.csv", index=False)
    t = pd.DataFrame(truth, columns=["date", "product_id", "true_demand", "sales", "stockout_morning", "policy"])
    t.to_csv(out / "true_demand.csv", index=False)
    g = t.groupby("policy")[["true_demand", "sales", "stockout_morning"]].mean()
    print(f"{len(tx)} борлуулалтын мөр, {a.products} бараа → {out}")
    print("алдагдсан эрэлт:", (1 - g["sales"] / g["true_demand"]).round(3).to_dict(),
          "нөөцгүй өглөөний хувь:", g["stockout_morning"].round(3).to_dict())


if __name__ == "__main__":
    main()
