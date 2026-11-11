"""Захиалгын төлөв (DQ-11): цуцлагдсан захиалга борлуулалтад орохгүй, буцаагдсан нь буцаалт болно,
анхны мөр хэвээр хадгалагдана. Amazon маягийн онлайн дэлгүүрийн өгөгдөлд зориулав."""
import datetime as dt

import numpy as np
import pandas as pd

from fcsys.engine import grid, ingest
from fcsys.engine import validate as dq

RAW = pd.DataFrame({
    "OrderDate": ["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02", "2024-01-03"],
    "ProductID": ["P1", "P1", "P1", "P2", "P2"],
    "Quantity": ["3", "5", "2", "4", "1"],
    "OrderID": ["A", "B", "C", "D", "E"],
    "OrderStatus": ["Delivered", "Cancelled", "Returned", "Pending", "canceled "],
}).astype(str)


def test_status_column_is_suggested():
    m = ingest.suggest_mapping(list(RAW.columns))
    assert m["order_status"] == "OrderStatus"
    assert m["product_id"] == "ProductID" and m["qty"] == "Quantity"


def test_cancelled_and_returned_rows_are_flagged_not_dropped():
    tx = ingest.parse_transactions(RAW, ingest.suggest_mapping(list(RAW.columns)))
    assert len(tx) == len(RAW)                                    # анхны мөр бүгд хадгалагдана (Z2)
    # «Returned» = буцаагдсан анхны захиалга → борлуулалт биш (давхар хасахгүйн тулд is_return биш)
    assert tx["is_cancelled"].tolist() == [False, True, True, False, True]
    assert tx["is_return"].tolist() == [False, False, False, False, False]
    assert tx["order_status"].tolist()[1] == "Cancelled"


def test_dq11_reported_and_cancelled_excluded_from_sales():
    tx = ingest.parse_transactions(RAW, ingest.suggest_mapping(list(RAW.columns)))
    res = dq.validate_transactions(tx, dt.date(2024, 12, 31))
    dq11 = [i for i in res.issues if i.rule_id == "DQ-11"]
    assert {(i.product_id, i.severity, i.original_value) for i in dq11} == {("P1", "info", "2"), ("P2", "info", "1")}
    assert "1 цуцлагдсан, 1 буцаагдсан" in next(i.message for i in dq11 if i.product_id == "P1")
    clean = tx[~tx["is_cancelled"]]                               # jobs._build_and_store-ийн дүрэм
    daily = grid.build_daily(clean, pd.Timestamp("2024-01-03"))
    sold = daily.groupby("product_id")["sales_qty"].sum().to_dict()
    assert sold == {"P1": 3.0, "P2": 4.0}                         # P1: 3 (5 цуцлагдсан, 2 буцаагдсан); P2: 4 (1 цуцлагдсан)


def test_no_status_column_keeps_old_behaviour():
    m = ingest.suggest_mapping(["date", "sku", "qty"])
    tx = ingest.parse_transactions(pd.DataFrame({"date": ["2024-01-01"], "sku": ["X"], "qty": ["2"]}), m)
    assert not tx["is_cancelled"].any() and tx["order_status"].isna().all()


def test_first_month_not_lost_when_first_sale_is_late_in_first_month():
    """Бүртгэл 1-нд эхэлсэн, бараа 3-нд анх зарагдсан → эхний сар бүтэн хэвээр (Amazon 2024 файлд 16 бараа хасагддаг байсан)."""
    from fcsys.engine.monthly import build_monthly
    days = pd.date_range("2020-01-01", "2020-03-31")
    tx = pd.DataFrame({"txn_date": list(days) + [pd.Timestamp("2020-01-03")], "product_ext_id": ["A"] * len(days) + ["B"],
                       "branch_ext_id": "ALL", "qty": 1.0, "unit": "ш", "amount": 1.0, "is_return": False})
    tx.loc[tx.index[-1] - 1, "txn_date"] = pd.Timestamp("2020-03-31")
    tx = pd.concat([tx, pd.DataFrame({"txn_date": pd.date_range("2020-01-03", "2020-03-31", freq="7D"),
                                      "product_ext_id": "B", "branch_ext_id": "ALL", "qty": 2.0, "unit": "ш",
                                      "amount": 1.0, "is_return": False})], ignore_index=True)
    daily = grid.build_daily(tx, pd.Timestamp("2020-03-31"))
    b = daily[daily.product_id == "B"].sort_values("day")
    assert b["day"].min() == pd.Timestamp("2020-01-01")
    m = build_monthly(b, "sales", pd.Timestamp("2020-03-31"))
    assert m.index[0] == pd.Timestamp("2020-01-01") and not np.isnan(m["y"].iloc[0])


def test_product_launched_later_still_starts_at_first_sale():
    tx = pd.DataFrame({"txn_date": [pd.Timestamp("2020-01-01"), pd.Timestamp("2020-03-10")], "product_ext_id": ["A", "C"],
                       "branch_ext_id": "ALL", "qty": 1.0, "unit": "ш", "amount": 1.0, "is_return": False})
    daily = grid.build_daily(tx, pd.Timestamp("2020-03-31"))
    assert daily[daily.product_id == "C"]["day"].min() == pd.Timestamp("2020-03-10")


def test_demand_month_corrected_for_stockout_and_sold_out_days():
    """Эрэлт (D): нөөцгүй ба «дууссан» өдрийн оронд нөөцтэй өдрийн дундаж — борлуулалт (S) өөрчлөгдөхгүй."""
    from fcsys.engine.monthly import build_monthly
    days = pd.date_range("2024-01-01", "2024-01-31")              # 31 өдөр, өдөрт эрэлт 10
    sales = [10.0] * 25 + [4.0] + [0.0] * 5                         # 26-нд 4 үлдсэн → дууссан, 27–31 нөөцгүй
    onhand = [50] * 25 + [4] + [0] * 5
    tx = pd.DataFrame({"txn_date": [d for d, q in zip(days, sales) if q > 0], "product_ext_id": "A", "branch_ext_id": "B",
                       "qty": [q for q in sales if q > 0], "unit": "ш", "amount": 1.0, "is_return": False})
    other = pd.DataFrame({"txn_date": days, "product_ext_id": "Z", "branch_ext_id": "B", "qty": 1.0, "unit": "ш",
                          "amount": 1.0, "is_return": False})          # салбар өдөр бүр ажилласан (бүртгэл дутуу биш)
    tx = pd.concat([tx, other], ignore_index=True)
    inv = pd.DataFrame({"date": days, "product_id": "A", "branch_id": "B", "on_hand": onhand,
                        "available": [o > 0 for o in onhand]})
    daily = grid.build_daily(tx, pd.Timestamp("2024-01-31"), inventory=inv)
    daily = daily[daily.product_id == "A"]
    assert daily.set_index("day").loc["2024-01-26", "day_state"] == "sold_out"
    assert (daily.day_state == "stockout").sum() == 5
    s = build_monthly(daily, "sales", pd.Timestamp("2024-01-31"))
    d = build_monthly(daily, "demand", pd.Timestamp("2024-01-31"))
    assert s["y"].iloc[0] == 254.0                                  # бодит борлуулалт
    assert abs(d["y"].iloc[0] - 310.0) < 1e-9                       # 25 бүтэн өдөр × 10 = 250 → ×31/25 = 310


def test_stockout_estimated_without_inventory():
    """Нөөцийн файлгүй: өдөрт ~10 зарагддаг бараа 5 хоног 0 → «нөөцгүй бололтой»; ховор бараанд 0 өдөр хэвийн."""
    days = pd.date_range("2024-01-01", "2024-03-31")
    rows = []
    for i, d in enumerate(days):
        if not (60 <= i < 65):
            rows.append((d, "FAST", 10.0))                        # 60–64-р өдөр зарагдаагүй
        if i % 9 == 0:
            rows.append((d, "SLOW", 1.0))                         # 9 хоногт нэг удаа
        rows.append((d, "Z", 1.0))                                # салбар өдөр бүр ажилласан
    tx = pd.DataFrame(rows, columns=["txn_date", "product_ext_id", "qty"]).assign(
        branch_ext_id="B", unit="ш", amount=1.0, is_return=False)
    daily = grid.build_daily(tx, pd.Timestamp("2024-03-31"))
    fast = daily[daily.product_id == "FAST"].set_index("day").day_state
    assert (fast.iloc[60:65] == "stockout_est").all() and (fast == "stockout_est").sum() == 5
    assert fast.iloc[59] == "sold_out"                            # тасалдлын өмнөх өдөр дууссан бололтой
    assert not (daily[daily.product_id == "SLOW"].day_state == "stockout_est").any()
    from fcsys.engine.monthly import build_monthly
    m = build_monthly(daily[daily.product_id == "FAST"], "demand", pd.Timestamp("2024-03-31"))
    assert abs(m.loc["2024-03-01", "y"] - 310.0) < 1e-9             # 26 өдөр × 10 → ×31/26 = 310
    assert abs(m.loc["2024-02-01", "y"] - 290.0) < 1e-9             # 2-29 «дууссан» ч бүтэн 10 → өөрчлөгдөхгүй
