"""Шинээр үүсгэсэн мөр (туршилт, ажил) хариу ирмэгц дараагийн хүсэлтэд харагдах ёстой.
Анхдагч scope-той yield-dependency нь commit-ийг хариуны дараа хийдэг тул ачаалалтай үед 404 гардаг байв
(Amazon өгөгдлийн шалгалтаар илэрсэн). Бүх endpoint get_conn-ийг scope="function"-оор авах ёстой."""
from pathlib import Path

API = Path(__file__).resolve().parents[1] / "fcsys" / "api"


def test_every_get_conn_dependency_commits_before_response():
    plain = [f"{p.relative_to(API)}:{i}" for p in API.rglob("*.py")
             for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
             if "Depends(get_conn)" in line]
    assert not plain, f"scope='function' дутуу: {plain}"

