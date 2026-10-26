"""ingest — файл унших, талбар зураглах, checksum тооцох (FR-D1–D3)."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np
import pandas as pd

REQUIRED_FIELDS = ["txn_date", "product_id", "branch_id", "qty", "unit"]
OPTIONAL_FIELDS = ["txn_id", "amount", "is_return"]

# Талбарын нэрийг таних түлхүүр үгс (англи, монгол) — зураглалын санал (UC-01 алхам 2)
_HINTS = {
    "txn_date": ["date", "txn_date", "огноо", "day", "sale_date"],
    "product_id": ["product", "item", "sku", "бүтээгдэхүүн", "item_id", "product_id"],
    "branch_id": ["branch", "store", "салбар", "shop", "store_id", "branch_id"],
    "qty": ["qty", "quantity", "units", "тоо", "хэмжээ", "sales"],
    "unit": ["unit", "uom", "нэгж"],
    "txn_id": ["txn_id", "transaction", "receipt", "баримт", "order_id"],
    "amount": ["amount", "revenue", "дүн", "total", "value"],
    "is_return": ["return", "буцаалт", "is_return"],
}

AUX_COLUMNS = {
    "price": ["date", "product_id", "branch_id", "price", "price_kind", "known_at"],
    "calendar": ["date", "branch_id", "is_open"],
    "inventory": ["date", "product_id", "branch_id", "on_hand", "available", "reliability"],
    "promotion": ["date_from", "date_to", "product_id", "branch_id", "promo_kind", "known_at"],
}


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_table(path: str | Path, nrows: int | None = None) -> pd.DataFrame:
    """CSV эсвэл Excel-ийг бүх баганыг текстээр уншина (утгыг өөрчлөхгүй)."""
    p = str(path).lower()
    if p.endswith((".xlsx", ".xlsm", ".xls")):
        df = pd.read_excel(path, dtype=str, nrows=nrows)
    else:
        df = pd.read_csv(path, dtype=str, nrows=nrows, keep_default_na=False,
                         sep=None, engine="python", encoding="utf-8-sig")
    df.columns = [str(c).strip() for c in df.columns]
    return df.fillna("")


def suggest_mapping(columns: list[str]) -> dict[str, str | None]:
    norm = {c: re.sub(r"[^a-zа-яөү0-9_]", "", c.lower()) for c in columns}
    mapping: dict[str, str | None] = {}
    used: set[str] = set()
    for field_, hints in _HINTS.items():
        found = None
        for hint in hints:  # эхлээд яг таарах, дараа нь агуулах
            for c, n in norm.items():
                if c not in used and n == hint:
                    found = c
                    break
            if found:
                break
        if not found:
            for hint in hints:
                for c, n in norm.items():
                    if c not in used and hint in n:
                        found = c
                        break
                if found:
                    break
        mapping[field_] = found
        if found:
            used.add(found)
    return mapping


def missing_required(columns: list[str], mapping: dict) -> list[str]:
    """DQ-01 (толгойн түвшин): заавал талбар зураглагдаагүй эсвэл файлд байхгүй."""
    cols = set(columns)
    return [f for f in REQUIRED_FIELDS if not mapping.get(f) or mapping[f] not in cols]


def _parse_dates(raw: pd.Series, date_format: str | None) -> pd.Series:
    if date_format:
        parsed = pd.to_datetime(raw, format=date_format, errors="coerce")
    else:
        parsed = pd.to_datetime(raw, errors="coerce", format="mixed", dayfirst=False)
    return parsed.dt.normalize()


def _to_float(raw: pd.Series) -> pd.Series:
    cleaned = raw.astype(str).str.replace(",", "", regex=False).str.strip()
    cleaned = cleaned.replace("", np.nan)
    return pd.to_numeric(cleaned, errors="coerce")


def _to_bool(raw: pd.Series) -> pd.Series:
    return raw.astype(str).str.strip().str.lower().isin(["1", "true", "yes", "y", "тийм", "t"])


def parse_transactions(df: pd.DataFrame, mapping: dict, date_format: str | None = None) -> pd.DataFrame:
    """Зураглалын дагуу нэгдсэн хэлбэрт оруулна. Уншигдаагүй утга NaN/NaT болж үлдэнэ
    (устгахгүй), validate модуль тэдгээрийг DQ-01, DQ-02-оор тэмдэглэнэ."""
    out = pd.DataFrame({"source_row": np.arange(2, len(df) + 2, dtype=int)})  # 1-р мөр = толгой
    out["txn_date_raw"] = df[mapping["txn_date"]].astype(str).values
    out["txn_date"] = _parse_dates(df[mapping["txn_date"]], date_format).values
    out["product_ext_id"] = df[mapping["product_id"]].astype(str).str.strip().values
    out["branch_ext_id"] = df[mapping["branch_id"]].astype(str).str.strip().values
    out["qty"] = _to_float(df[mapping["qty"]]).values
    out["unit"] = df[mapping["unit"]].astype(str).str.strip().values
    out["txn_id"] = (df[mapping["txn_id"]].astype(str).str.strip().values
                     if mapping.get("txn_id") else None)
    out["amount"] = _to_float(df[mapping["amount"]]).values if mapping.get("amount") else np.nan
    if mapping.get("is_return"):
        out["is_return"] = _to_bool(df[mapping["is_return"]]).values
    else:
        out["is_return"] = False
    out.loc[out["qty"] < 0, "is_return"] = True   # сөрөг хэмжээ = буцаалт (DQ-05)
    return out


def parse_aux(kind: str, path: str | Path) -> pd.DataFrame:
    """Туслах файл (үнэ, календарь, нөөц, урамшуулал) — тогтмол баганын нэртэй."""
    df = read_table(path)
    need = [c for c in AUX_COLUMNS[kind] if c not in ("known_at", "reliability", "promo_kind",
                                                      "on_hand", "product_id", "branch_id")]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise ValueError(f"{kind} файлд багана дутуу: {', '.join(missing)}")
    out = pd.DataFrame()
    for c in df.columns:
        if c in ("date", "known_at", "date_from", "date_to"):
            out[c] = _parse_dates(df[c], None)
        elif c in ("price", "on_hand"):
            out[c] = _to_float(df[c])
        elif c in ("is_open", "available"):
            out[c] = _to_bool(df[c])
        else:
            out[c] = df[c].astype(str).str.strip()
    if kind == "price":
        out["price_kind"] = out.get("price_kind", "actual")
        out["price_kind"] = out["price_kind"].replace("", "actual")
        if "known_at" not in out:
            out["known_at"] = out["date"]
        out["known_at"] = out["known_at"].fillna(out["date"])
    if kind == "promotion" and "known_at" not in out:
        out["known_at"] = out["date_from"]
    if kind == "inventory" and "reliability" not in out:
        out["reliability"] = "unverified"
    return out
