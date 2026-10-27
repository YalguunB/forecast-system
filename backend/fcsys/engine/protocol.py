"""Туршилтын протокол — өгөгдөл болгон хадгалагдана (Z4, FR-M2, §2.5.5)."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from .models import MODEL_REGISTRY

DEFAULT_PROTOCOL: dict = {
    "grain": "month",                  # таамаглал сарын түвшинд (диплом §2.4)
    "train_min_months": 24,
    "val_months": 12,
    "test_months": 12,
    "step_months": 1,
    "H": 12,
    "horizons": [1, 3, 12],            # сар, улирал, жил
    "mase_m": 12,
    "feature_set": "none",
    "models": [
        {"name": "ma", "params": {"window": 3}},
        {"name": "naive", "params": {}},
        {"name": "snaive", "params": {"m": 12}},
        {"name": "ets", "params": {"seasonal": "add"}},
        {"name": "ets", "params": {"seasonal": "add", "trend": "add", "damped": True}},
        {"name": "sarima", "params": {"order": [1, 1, 1], "seasonal_order": [0, 1, 1]}},
        {"name": "croston", "params": {"alpha": 0.1}},
        {"name": "sba", "params": {"alpha": 0.1}},
    ],
    "baseline": {"name": "ma", "params": {"window": 3}},
    "fallback": {"name": "ma", "params": {"window": 3}},
    "selection_metric": "WAPE",
    "selection_level": "global",      # series | group | global
    "sample": {"min_length_months": 24, "max_series": 200, "classes": None, "max_zero_share": None,
               "branches": None, "categories": None},
    "seed": 20261025,
}


def suggest_protocol(n_months: int) -> dict:
    """Өгөгдлийн бүтэн сарын тоонд тохирох хуваалт. ≥ 48 сар: 24 / 12 / 12; 36–47: сургалт = n − 24;
    24–35: сургалт 12, үлдсэнийг validation, тестэд тэнцүү (жилийн хүрээг үнэлэх боломжгүй)."""
    p = deepcopy(DEFAULT_PROTOCOL)
    if n_months >= 48:
        return p
    if n_months >= 36:
        p["train_min_months"] = n_months - 24
    else:
        rest = max(n_months - 12, 6)
        p["train_min_months"] = 12
        p["val_months"] = rest // 2
        p["test_months"] = rest - rest // 2
    p["sample"]["min_length_months"] = p["train_min_months"] + p["val_months"] + p["test_months"]
    return p


class ProtocolError(ValueError):
    pass


LEGACY_MESSAGE = ("Энэ нь сарын түвшинд шилжихээс өмнө үүсгэсэн хуучин (өдрийн) таамаглал тул нээх боломжгүй. "
                  "«Таамаглал бэлтгэх» хэсэгт шинэ таамаглал үүсгэнэ үү — өгөгдлөө дахин оруулах шаардлагагүй.")


def is_monthly(protocol: dict | None) -> bool:
    """Хуучин өдрийн протокол (H = 30, val_days …) уу, шинэ сарын протокол уу."""
    return bool(protocol) and protocol.get("grain") == "month"


def normalize_protocol(p: dict | None) -> dict:
    out = deepcopy(DEFAULT_PROTOCOL)
    for k, v in (p or {}).items():
        if k == "sample" and isinstance(v, dict):
            out["sample"].update(v)
        else:
            out[k] = v
    errors = []
    if out.get("grain") != "month":
        errors.append("grain = month (таамаглал сарын түвшинд)")
    if out["H"] != 12 or sorted(out["horizons"]) != [1, 3, 12]:
        errors.append("H = 12, horizons = {1, 3, 12} (сар, улирал, жил) байх ёстой")
    if out["train_min_months"] < 12 or out["val_months"] < 3 or out["test_months"] < 3:
        errors.append("сургалт ≥ 12 сар, validation ба тест тус бүр ≥ 3 сар")
    if out["step_months"] < 1:
        errors.append("step_months ≥ 1")
    if out["selection_level"] not in ("series", "group", "global"):
        errors.append("selection_level ∈ {series, group, global}")
    if out["selection_metric"] not in ("WAPE", "MAE", "RMSE", "MASE", "RMSSE"):
        errors.append("selection_metric ∈ {WAPE, MAE, RMSE, MASE, RMSSE}")
    names = set()
    for m in [*out["models"], out["baseline"], out["fallback"]]:
        if m.get("name") not in MODEL_REGISTRY:
            errors.append(f"загвар '{m.get('name')}' бүртгэгдээгүй ({sorted(MODEL_REGISTRY)})")
        names.add(m.get("name"))
    keys = [(m["name"], json.dumps(m.get("params", {}), sort_keys=True)) for m in out["models"]]
    if len(keys) != len(set(keys)):
        errors.append("ижил загвар, параметрийн хувилбар давхардсан")
    base = (out["baseline"]["name"], json.dumps(out["baseline"].get("params", {}), sort_keys=True))
    if base not in keys:
        errors.append("суурь загвар (baseline) загваруудын жагсаалтад байх ёстой (FR-M1)")
    if errors:
        raise ProtocolError("; ".join(errors))
    return out


def canonical_hash(obj) -> str:
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def derive_seed(base_seed: int, series_id: int) -> int:
    """Цуваа бүрийн seed нь үндсэн seed ба series_id-аас — багцын хуваалтаас үл хамаарна (NFR-1)."""
    h = hashlib.sha256(f"{base_seed}:{series_id}".encode()).hexdigest()
    return int(h[:8], 16) % (2 ** 31 - 1)
