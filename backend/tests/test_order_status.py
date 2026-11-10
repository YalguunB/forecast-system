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
