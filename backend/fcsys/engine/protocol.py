"""Туршилтын протокол — өгөгдөл болгон хадгалагдана (Z4, FR-M2, §2.5.5)."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from .models import MODEL_REGISTRY

DEFAULT_PROTOCOL: dict = {
    "train_min_days": 180,
    "val_days": 60,
    "test_days": 90,
    "step_days": 7,
    "H": 30,
    "horizons": [7, 14, 30],
    "mase_m": 7,
    "feature_set": "none",
    "models": [
        {"name": "naive", "params": {}},
        {"name": "snaive", "params": {"m": 7}},
        {"name": "ets", "params": {"seasonal": "add"}},
        {"name": "croston", "params": {"alpha": 0.1}},
        {"name": "sba", "params": {"alpha": 0.1}},
    ],
    "baseline": {"name": "snaive", "params": {"m": 7}},
    "fallback": {"name": "snaive", "params": {"m": 7}},
    "selection_metric": "MASE",
    "selection_level": "global",      # series | group | global — нээлттэй асуудал, анхдагч global
    "sample": {"min_length_days": 330, "max_series": 200, "classes": None, "max_zero_share": None},
    "seed": 20261025,
}


class ProtocolError(ValueError):
    pass


def normalize_protocol(p: dict | None) -> dict:
    out = deepcopy(DEFAULT_PROTOCOL)
    for k, v in (p or {}).items():
        if k == "sample" and isinstance(v, dict):
            out["sample"].update(v)
        else:
            out[k] = v
    errors = []
    if out["H"] != 30 or sorted(out["horizons"]) != [7, 14, 30]:
        errors.append("H = 30, horizons = {7, 14, 30} байх ёстой (§2.5.5)")
    if out["train_min_days"] < 60 or out["val_days"] < out["H"] or out["test_days"] < out["H"]:
        errors.append("validation, тестийн урт H-аас багагүй, сургалт ≥ 60 хоног байна")
    if out["step_days"] < 1:
        errors.append("step_days ≥ 1")
    if out["selection_level"] not in ("series", "group", "global"):
        errors.append("selection_level ∈ {series, group, global}")
    if out["selection_metric"] not in ("MASE", "RMSSE", "MAE", "WAPE"):
        errors.append("selection_metric ∈ {MASE, RMSSE, MAE, WAPE}")
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
