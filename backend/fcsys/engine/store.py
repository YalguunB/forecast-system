"""Өгөгдлийн санаас унших, бичих туслах (модуль бүр DB-ээс уншиж, DB-д бичнэ — §4.4)."""
from __future__ import annotations

import datetime as dt
import math
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
import psycopg


def copy_rows(conn: psycopg.Connection, table: str, columns: Sequence[str], rows: Iterable[Sequence]) -> int:
    n = 0
    cols = ", ".join(columns)
    with conn.cursor() as cur, cur.copy(f"COPY {table} ({cols}) FROM STDIN") as cp:
        for r in rows:
            cp.write_row([_clean(v) for v in r])
            n += 1
    return n


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.date()
    if v is pd.NaT:
        return None
    return v


def load_transactions(conn, version_id: int) -> pd.DataFrame:
    rows = conn.execute(
        "SELECT source_row, txn_id, txn_date, txn_date_raw, product_ext_id, branch_ext_id, qty, unit, "
        "amount, is_return, is_cancelled FROM raw.raw_transaction WHERE dataset_version_id = %s ORDER BY source_row",
        (version_id,)).fetchall()
    df = pd.DataFrame(rows, columns=["source_row", "txn_id", "txn_date", "txn_date_raw", "product_ext_id",
                                     "branch_ext_id", "qty", "unit", "amount", "is_return", "is_cancelled"])
    df["txn_date"] = pd.to_datetime(df["txn_date"])
    for c in ("qty", "amount"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    return df


def load_calendar(conn, version_id: int) -> pd.DataFrame:
    rows = conn.execute("SELECT branch_id, day AS date, is_open FROM curated.calendar_day "
                        "WHERE dataset_version_id = %s", (version_id,)).fetchall()
    df = pd.DataFrame(rows, columns=["branch_id", "date", "is_open"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_inventory(conn, version_id: int) -> pd.DataFrame:
    rows = conn.execute(
        "SELECT s.product_id, s.branch_id, i.day AS date, i.on_hand, i.available, i.reliability "
        "FROM curated.inventory_snapshot i JOIN curated.series s ON s.id = i.series_id "
        "WHERE i.dataset_version_id = %s", (version_id,)).fetchall()
    df = pd.DataFrame(rows, columns=["product_id", "branch_id", "date", "on_hand", "available", "reliability"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_daily(conn, version_id: int, series_ids: Sequence[int] | None = None) -> dict[int, pd.DataFrame]:
    q = ("SELECT series_id, day, sales_qty, day_state::text AS day_state FROM curated.daily_series "
         "WHERE dataset_version_id = %s")
    params: list = [version_id]
    if series_ids is not None:
        q += " AND series_id = ANY(%s)"
        params.append(list(series_ids))
    rows = conn.execute(q + " ORDER BY series_id, day", params).fetchall()
    df = pd.DataFrame(rows, columns=["series_id", "day", "sales_qty", "day_state"])
    df["day"] = pd.to_datetime(df["day"])
    return {int(sid): g.reset_index(drop=True) for sid, g in df.groupby("series_id")}


def load_holidays(conn) -> set[dt.date]:
    return {r["day"] for r in conn.execute("SELECT day FROM curated.holiday").fetchall()}
