"""Менежерт харуулах нэрс (frontend/src/labels.js-тэй ижил байлгана)."""
from __future__ import annotations

MODEL_LABELS = {
    "ma": "3 сарын дундаж", "naive": "Өнгөрсөн сар", "snaive": "Өмнөх өгөгдлийн мөн сар",
    "ets": "Чиг хандлага, улирал", "sarima": "Улирлын загвар", "croston": "Тэгшитгэсэн дундаж (Croston)",
    "sba": "Тэгшитгэсэн дундаж (SBA)", "combo": "Хосолсон арга",
}


def model_label(model: str | None, params: dict | None = None) -> str:
    """Загварын код + параметрийг монгол нэр болгоно (ETS-ийн чиг хандлагатай хувилбарыг ялгана)."""
    if not model:
        return ""
    p = params or {}
    if model == "ets" and p.get("trend"):
        return "Чиг хандлага, улирал (өсөлттэй)"
    return MODEL_LABELS.get(model, model)
