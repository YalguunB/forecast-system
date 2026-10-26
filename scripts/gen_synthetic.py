"""Синтетик, M5-тай төстэй өгөгдөл үүсгэгч (seed-тэй, дахин гаргах боломжтой).

Зорилго нь системийн бүх дүрэм, төлвийг шалгах: тасалдсан (intermittent) цуваа,
нөөцгүй өдөр (stockout), хаалттай өдөр, бүртгэлийн тасралт, буцаалт, баяр,
урамшуулал, нэгжийн хөрвүүлэлт, буруу огноо/хэмжээ, давхардал, богино цуваа,
код солигдсон бүтээгдэхүүн. Энэ нь бодит байгууллагын өгөгдөл БИШ; үр дүнг
бодит нарийвчлал гэж тайлагнахгүй.

Хэрэглээ:  python scripts/gen_synthetic.py --out data/synthetic --seed 42
Гаралт: transactions.csv, prices.csv, calendar.csv, inventory.csv
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

TSAGAAN_SAR = {2024: "2024-02-10", 2025: "2025-03-01", 2026: "2026-02-20"}


def holidays(start, end) -> dict[pd.Timestamp, float]:
    """Баярын нөлөө (үржвэр) — Цагаан сарын өмнө өсөлт, баярын өдөр уналт, Наадам."""
    eff = {}
    for y in range(start.year, end.year + 1):
        if y in TSAGAAN_SAR:
            d0 = pd.Timestamp(TSAGAAN_SAR[y])
            for k in range(1, 8):
                eff[d0 - pd.Timedelta(days=k)] = 1.0 + 0.12 * (8 - k)   # баярын өмнөх худалдаа
            for k in range(3):
                eff[d0 + pd.Timedelta(days=k)] = 0.35
        for d in range(11, 16):
            eff[pd.Timestamp(f"{y}-07-{d}")] = 0.6
        eff[pd.Timestamp(f"{y}-12-31")] = 1.5
    return eff


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/synthetic")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--start", default="2024-03-01")
    ap.add_argument("--end", default="2026-09-30")
    ap.add_argument("--products", type=int, default=30)
    ap.add_argument("--branches", type=int, default=3)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    start, end = pd.Timestamp(a.start), pd.Timestamp(a.end)
    days = pd.date_range(start, end, freq="D")
    hol = holidays(start, end)
    branches = [f"B{b + 1:02d}" for b in range(a.branches)]
    products = [f"P{p + 1:03d}" for p in range(a.products)]

    # Салбарын календарь: Цагаан сарын 1-р өдөр хаалттай + санамсаргүй засварын өдөр
    cal_rows = []
    closed = set()
    for b in branches:
        maint = set(rng.choice(len(days), size=4, replace=False))
        for i, d in enumerate(days):
            is_closed = d in {pd.Timestamp(v) for v in TSAGAAN_SAR.values()} or i in maint
            if is_closed:
                closed.add((b, d))
            cal_rows.append((d.date(), b, 0 if is_closed else 1))
    # B02 бүртгэлийн тасралт: 3 өдөр гүйлгээ огт байхгүй (календарь нээлттэй)
    gap_b, gap_days = "B02", pd.date_range("2025-10-14", periods=3)

    tx, inv_rows, price_rows = [], [], []
    replaced_lams: list[float] = []
    txn_counter = 0
    for p_idx, p in enumerate(products):
        kind = "smooth" if p_idx % 3 == 0 else ("intermittent" if p_idx % 3 == 1 else "erratic")
        base = {"smooth": rng.uniform(8, 25), "intermittent": rng.uniform(0.2, 0.8),
                "erratic": rng.uniform(2, 6)}[kind]
        weekly = 1 + rng.uniform(0.1, 0.4) * np.sin(2 * np.pi * (np.arange(7) - rng.integers(7)) / 7)
        price0 = float(rng.choice([1500, 2900, 4500, 8900, 12000]))
        launch = start
        if p_idx >= a.products - 2:                       # богино цуваа (DQ-09)
            launch = pd.Timestamp("2026-03-01")
        for b_idx, b in enumerate(branches):
            scale = [1.0, 0.7, 0.45][b_idx % 3]
            trend = np.linspace(1.0, 1.0 + rng.uniform(-0.2, 0.3), len(days))
            # нөөцгүй үе: B01-д хүртээмж найдвартай бүртгэгдэнэ
            so = np.zeros(len(days), dtype=bool)
            for _ in range(rng.integers(1, 4)):
                s0 = rng.integers(0, len(days) - 10)
                so[s0:s0 + rng.integers(2, 7)] = True
            # урамшуулал: 4 удаа, 5–10 хоног, эрэлт 1.4×, үнэ 0.85×
            promo = np.zeros(len(days), dtype=bool)
            for _ in range(4):
                s0 = rng.integers(0, len(days) - 12)
                promo[s0:s0 + rng.integers(5, 11)] = True
            for i, d in enumerate(days):
                if d < launch:
                    continue
                if p == products[-3] and b == branches[-1] and d > pd.Timestamp("2025-12-31"):
                    continue                              # код солигдсон (DQ-07): дараагийнх нь P999
                lam = base * scale * weekly[d.dayofweek] * trend[i] * hol.get(d, 1.0) * (1.4 if promo[i] else 1.0)
                if p == products[-3] and b == branches[-1]:
                    replaced_lams.append(lam)
                q = rng.poisson(lam) if kind != "erratic" else rng.poisson(lam * rng.gamma(0.6, 1 / 0.6))
                if (b, d) in closed or (b == gap_b and d in gap_days):
                    q = 0
                if so[i]:
                    q = 0
                if b == "B01":
                    inv_rows.append((d.date(), p, b, 0 if so[i] else int(rng.integers(5, 60)),
                                     0 if so[i] else 1, "reliable"))
                if q <= 0:
                    continue
                n_receipts = 1 if q < 4 else int(rng.integers(1, 4))
                parts = np.diff(np.sort(np.r_[0, rng.integers(0, q + 1, n_receipts - 1), q]))
                for part in parts:
                    if part <= 0:
                        continue
                    txn_counter += 1
                    unit = "ширхэг"
                    qty = int(part)
                    if p == products[4] and txn_counter % 37 == 0 and qty >= 12:   # нэгж: хайрцаг (×12)
                        unit, qty = "хайрцаг", qty // 12
                        if qty == 0:
                            unit, qty = "ширхэг", int(part)
                    price = price0 * (0.85 if promo[i] else 1.0)
                    tx.append([f"T{txn_counter:08d}", d.strftime("%Y-%m-%d"), p, b, qty, unit, round(qty * price, 0), 0])
            # Үнэ: сар бүрийн бодит үнэ + нэг батлагдсан төлөвлөгөө (урьдчилан мэдэгдсэн)
            for d in pd.date_range(max(launch, start), end, freq="MS"):
                price_rows.append((d.date(), p, b, price0, "actual", d.date()))
            plan_day = pd.Timestamp("2026-10-01")
            price_rows.append((plan_day.date(), p, b, round(price0 * 1.05), "approved_plan",
                               (plan_day - pd.Timedelta(days=20)).date()))

    # Код солигдсон бүтээгдэхүүн P999: P028-ийг B03-т 2026-01-05-наас орлоно
    rep_lam = float(np.mean(replaced_lams[-60:]))        # ижил түвшин — DQ-07 сэжиг үүснэ
    for d in pd.date_range("2026-01-05", end):
        q = rng.poisson(rep_lam)
        if q > 0:
            txn_counter += 1
            tx.append([f"T{txn_counter:08d}", d.strftime("%Y-%m-%d"), "P999", branches[-1], q, "ширхэг", q * 3000, 0])

    df = pd.DataFrame(tx, columns=["receipt_no", "sale_date", "item", "store", "quantity", "uom", "revenue", "is_return"])
    # Буцаалт: 0.3% мөрийг сөрөг хэмжээтэй буцаалтаар нэмнэ
    ret = df.sample(frac=0.003, random_state=a.seed).copy()
    ret["receipt_no"] = ret["receipt_no"] + "R"
    ret["quantity"] = -ret["quantity"].clip(upper=2)
    ret["revenue"] = -ret["revenue"].abs()
    ret["is_return"] = 1
    df = pd.concat([df, ret], ignore_index=True)
    # Өгөгдлийн алдаа: буруу огноо, тоо биш хэмжээ, ирээдүйн огноо, давхардал
    bad = df.sample(n=6, random_state=a.seed + 1).copy().astype({"quantity": object})
    df = df.astype({"quantity": object})
    bad.loc[bad.index[:3], "sale_date"] = ["2025-13-45", "31/02/2025", "unknown"]
    bad.loc[bad.index[3], "quantity"] = "abc"
    bad.loc[bad.index[4], "sale_date"] = "2031-01-01"
    bad["receipt_no"] = bad["receipt_no"] + "X"
    dups = df.sample(n=5, random_state=a.seed + 2)
    df = pd.concat([df, bad, dups], ignore_index=True).sample(frac=1, random_state=a.seed).reset_index(drop=True)
    df.to_csv(out / "transactions.csv", index=False)

    pd.DataFrame(price_rows, columns=["date", "product_id", "branch_id", "price", "price_kind", "known_at"]) \
        .to_csv(out / "prices.csv", index=False)
    pd.DataFrame(cal_rows, columns=["date", "branch_id", "is_open"]).to_csv(out / "calendar.csv", index=False)
    pd.DataFrame(inv_rows, columns=["date", "product_id", "branch_id", "on_hand", "available", "reliability"]) \
        .to_csv(out / "inventory.csv", index=False)
    print(f"{len(df)} гүйлгээ, {len(products) * len(branches) + 1} цуваа, {start.date()}–{end.date()} → {out}")


if __name__ == "__main__":
    main()
