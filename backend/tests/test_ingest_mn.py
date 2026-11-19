"""Монгол толгойтой файлын баганыг таних (менежерийн хэрэглэгчийн тестээр илэрсэн асуудлууд)."""
from fcsys.engine.ingest import aux_missing_message, match_aux_columns, parse_aux, suggest_mapping


def test_product_code_column_recognised():
    m = suggest_mapping(["Баримт №", "Огноо", "Барааны код", "Барааны нэр", "Салбар", "Тоо ширхэг", "Нийт дүн"])
    assert m["product_id"] == "Барааны код" and m["product_name"] == "Барааны нэр"
    assert m["txn_date"] == "Огноо" and m["qty"] == "Тоо ширхэг" and m["branch_id"] == "Салбар"


def test_product_code_not_taken_from_branch_or_category_code():
    m = suggest_mapping(["Огноо", "Салбарын код", "Ангиллын код", "Барааны нэр", "Тоо"])
    assert m["product_id"] is None and m["branch_id"] == "Салбарын код"


def test_inventory_mongolian_headers(tmp_path):
    f = tmp_path / "noots.csv"
    f.write_text("Огноо,Барааны код,Салбар,Үлдэгдэл,Борлуулах боломжтой,Найдвартай\n"
                 "2026-09-01,P001,Төв салбар,35,1,найдвартай\n2026-09-02,P001,Төв салбар,0,0,reliable\n",
                 encoding="utf-8")
    out = parse_aux("inventory", f)
    assert list(out["on_hand"]) == [35.0, 0.0] and list(out["available"]) == [True, False]
    assert set(out["reliability"]) == {"reliable"} and str(out["date"].iloc[0])[:10] == "2026-09-01"


def test_inventory_with_only_stock_level(tmp_path):
    f = tmp_path / "noots.csv"
    f.write_text("Огноо,Код,Салбар,Үлдэгдэл\n2026-09-01,P1,B1,5\n2026-09-02,P1,B1,0\n", encoding="utf-8")
    out = parse_aux("inventory", f)
    assert list(out["available"]) == [True, False] and set(out["reliability"]) == {"unverified"}


def test_missing_aux_columns_message_is_mongolian():
    _, missing = match_aux_columns("inventory", ["Бараа", "Тоо"])
    assert missing == ["date"]
    msg = aux_missing_message("inventory", missing, ["Бараа", "Тоо"])
    assert "Нөөцийн үлдэгдлийн файлаас «Огноо»" in msg and "Error" not in msg
