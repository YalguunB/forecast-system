"""validate — өгөгдлийн чанарын дүрэм DQ-01–DQ-11 (Хүснэгт 3.9, FR-D4–D6, D10).

Дүрэм бүр асуудлын жагсаалт буцаана; мөрийг устгахгүй, утгыг дарж бичихгүй.
«Блоклох» асуудал нээлттэй байхад хувилбар таамаглалд ашиглагдахгүй.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

MIN_SERIES_DAYS = 330          # DQ-09, §2.5.5
QUARANTINE_BLOCK_SHARE = 0.01  # DQ-02: карантины хувь үүнээс их бол блоклоно
MAX_ROW_ISSUES_PER_RULE = 500  # нэг дүрмээр мөр бүрийн асуудлыг хязгаарлах (нэгтгэсэн мөр нэмэгдэнэ)


@dataclass
class Issue:
    rule_id: str
    severity: str             # blocking | warning | info
    message: str
    product_id: str | None = None
    branch_id: str | None = None
    day: dt.date | None = None
    source_row: int | None = None
    original_value: str | None = None


@dataclass
class ValidationResult:
    issues: list[Issue] = field(default_factory=list)
    quarantined_rows: set[int] = field(default_factory=set)

    @property
    def blocking(self) -> bool:
        return any(i.severity == "blocking" for i in self.issues)


def _row_issues(res: ValidationResult, rule: str, sev: str, rows: pd.DataFrame, msg: str,
                value_col: str) -> None:
    for r in rows.head(MAX_ROW_ISSUES_PER_RULE).itertuples(index=False):
        res.issues.append(Issue(rule, sev, msg, r.product_ext_id or None, r.branch_ext_id or None,
                                None if pd.isna(r.txn_date) else r.txn_date.date(),
                                int(r.source_row), str(getattr(r, value_col))))
    if len(rows) > MAX_ROW_ISSUES_PER_RULE:
        res.issues.append(Issue(rule, sev, f"{msg}: нийт {len(rows)} мөр "
                                f"(эхний {MAX_ROW_ISSUES_PER_RULE}-г жагсаав)"))


def numeric_share(values: pd.Series) -> float:
    """Утгын хэдэн хувь нь тоо вэ (нэгжийн баганад үнэ зураглагдсан эсэхийг илрүүлэх)."""
    v = values.astype(str).str.strip()
    v = v[v != ""]
    if v.empty:
        return 0.0
    return float(pd.to_numeric(v.str.replace(",", "", regex=False), errors="coerce").notna().mean())


def validate_transactions(tx: pd.DataFrame, today: dt.date, unit_conversions: list[dict] | None = None,
                          prices: pd.DataFrame | None = None) -> ValidationResult:
    res = ValidationResult()
    n = len(tx)

    # DQ-01 — заавал талбар хоосон эсвэл төрөл буруу (хэмжээ тоо биш) → блоклох
    bad = tx[tx["qty"].isna() | (tx["product_ext_id"] == "") | (tx["branch_ext_id"] == "")
             | (tx["unit"] == "")]
    if len(bad):
        _row_issues(res, "DQ-01", "blocking", bad, "Заавал талбар хоосон эсвэл хэмжээ тоо биш", "qty")
        res.quarantined_rows.update(bad["source_row"].astype(int))

    # DQ-02 — огноо уншигдахгүй эсвэл ирээдүйн огноо → карантин; олон бол блоклох
    future = tx["txn_date"].notna() & (tx["txn_date"].dt.date > today)
    bad_date = tx[tx["txn_date"].isna() | future]
    if len(bad_date):
        _row_issues(res, "DQ-02", "warning", bad_date,
                    "Огноо уншигдсангүй эсвэл ирээдүйн огноо — мөр карантинд", "txn_date_raw")
        res.quarantined_rows.update(bad_date["source_row"].astype(int))
        share = len(bad_date) / max(n, 1)
        if share > QUARANTINE_BLOCK_SHARE:
            res.issues.append(Issue("DQ-02", "blocking",
                                    f"Огнооны алдаатай мөр {len(bad_date)} ({share:.1%}) — "
                                    f"{QUARANTINE_BLOCK_SHARE:.0%}-аас их тул хувилбарыг блоклов"))

    ok = tx[~tx["source_row"].isin(res.quarantined_rows)]
    # DQ-11 — цуцлагдсан захиалга → борлуулалтад тооцохгүй (анхны мөр хадгалагдана), мэдээлэл
    if "is_cancelled" in ok and ok["is_cancelled"].any():
        canc = ok[ok["is_cancelled"]]
        from .ingest import RETURN_STATUSES
        st = canc["order_status"].astype(str).str.strip().str.lower() if "order_status" in canc else None
        for (pid, bid), g in canc.groupby(["product_ext_id", "branch_ext_id"]):
            n_ret = int(st.loc[g.index].isin(RETURN_STATUSES).sum()) if st is not None else 0
            n_can = len(g) - n_ret
            what = ", ".join(x for x in (f"{n_can} цуцлагдсан" if n_can else "", f"{n_ret} буцаагдсан" if n_ret else "") if x)
            res.issues.append(Issue("DQ-11", "info",
                                    f"{what} захиалга — борлуулалтад тооцоогүй (анхны мөр хадгалагдсан)",
                                    pid, bid, original_value=str(len(g))))
        ok = ok[~ok["is_cancelled"]]

    # DQ-03 — давхардсан мөр → автоматаар нэгтгэхгүй, жагсаана
    key = ["txn_date", "product_ext_id", "branch_ext_id"]
    if ok["txn_id"].notna().any() and (ok["txn_id"].fillna("") != "").any():
        key = key + ["txn_id"]
    else:
        key = key + ["qty", "amount"]
    dups = ok[ok.duplicated(subset=key, keep="first")]
    if len(dups):
        _row_issues(res, "DQ-03", "warning", dups,
                    "Давхардсан мөр (эхнийхтэй ижил түлхүүртэй) — шийдвэр шаардлагатай", "qty")

    # DQ-04 — нэг бүтээгдэхүүнд олон хэмжих нэгж → хөрвүүлэлт шаардана
    conv = {(c.get("product_id", "*"), c["from"]) for c in (unit_conversions or [])}
    units = ok.groupby("product_ext_id")["unit"].unique()
    for pid, us in units.items():
        if len(us) > 1:
            base = pd.Series(ok.loc[ok.product_ext_id == pid, "unit"]).mode().iloc[0]
            unconverted = [u for u in us if u != base and (pid, u) not in conv and ("*", u) not in conv]
            if unconverted:
                shown = ", ".join(sorted(map(str, us))[:5]) + (f" … (нийт {len(us)})" if len(us) > 5 else "")
                hint = (" — нэгжийн баганад тоо байна; буруу багана (жишээ нь үнэ) зураглагдсан байж магадгүй"
                        if numeric_share(pd.Series(us)) > 0.8 else "")
                res.issues.append(Issue("DQ-04", "blocking",
                                        f"{pid}: олон нэгж [{shown}]; «{base}» руу хөрвүүлэлт тодорхойлоогүй{hint}",
                                        product_id=pid, original_value=shown[:200]))

    # DQ-05 — сөрөг хэмжээ, буцаалт → тусад нь хадгалж цэвэр борлуулалт тооцно
    ret = ok[ok["is_return"]]
    if len(ret):
        g = ret.groupby(["product_ext_id", "branch_ext_id"]).size()
        for (pid, bid), cnt in g.items():
            res.issues.append(Issue("DQ-05", "warning",
                                    f"{cnt} буцаалтын мөр — тусад нь хадгалж цэвэр борлуулалтаас хасав "
                                    f"(сөрөг эрэлт гэж тооцохгүй)", pid, bid, original_value=str(cnt)))

    # DQ-10 — «бодит» үнэ хүчинтэй болохоосоо өмнө мэдэгдсэн гэж бичигдсэн → блоклох
    if prices is not None and len(prices):
        actual = prices[(prices["price_kind"] == "actual") & (prices["known_at"] < prices["date"])]
        for r in actual.head(MAX_ROW_ISSUES_PER_RULE).itertuples(index=False):
            res.issues.append(Issue("DQ-10", "blocking",
                                    "«Бодит» үнэ хүчинтэй огнооноосоо өмнө мэдэгдсэн гэж тэмдэглэгдсэн; "
                                    "таамаглах эхлэлийн оролтод ирээдүйн мэдээлэл орох эрсдэлтэй",
                                    r.product_id, r.branch_id, r.date.date(),
                                    original_value=f"known_at={r.known_at.date()}"))
    return res


def series_level_checks(daily: pd.DataFrame) -> list[Issue]:
    """Өдрийн цуваа байгуулсны дараах шалгалт: DQ-06, DQ-07, DQ-08, DQ-09.
    daily: product_id, branch_id, day, sales_qty, day_state."""
    issues: list[Issue] = []
    spans = {}
    for (pid, bid), g in daily.groupby(["product_id", "branch_id"], sort=True):
        g = g.sort_values("day")
        n_days = len(g)
        spans[(pid, bid)] = (g["day"].iloc[0], g.loc[g.sales_qty > 0, "day"].max(), n_days,
                             g.loc[g.sales_qty > 0, "sales_qty"].mean())
        # DQ-08 — гүйлгээгүй өдөр төлөвтэй болсон тухай мэдээлэл (0 болгоогүй)
        no_txn = g[g.day_state != "sold"]
        if len(no_txn):
            counts = no_txn.day_state.value_counts().to_dict()
            issues.append(Issue("DQ-08", "info",
                                "Гүйлгээгүй өдөр төлөвтэй боллоо: "
                                + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())),
                                pid, bid, original_value=str(len(no_txn))))
        # DQ-09 — цуваа богино
        if n_days < MIN_SERIES_DAYS:
            issues.append(Issue("DQ-09", "warning",
                                f"Цувааны урт {n_days} хоног (< {MIN_SERIES_DAYS}) — үндсэн харьцуулалтад "
                                "орохгүй, тусдаа бүлэгт тайлагнана", pid, bid, original_value=str(n_days)))
        # DQ-06 — статистик хэт утга (median + 8·MAD), устгахгүй
        pos = g.loc[g.sales_qty > 0, "sales_qty"]
        if len(pos) >= 20:
            med = pos.median()
            mad = (pos - med).abs().median()
            if mad > 0:
                out = g[(g.sales_qty > med + 8 * 1.4826 * mad)]
                for r in out.head(20).itertuples(index=False):
                    issues.append(Issue("DQ-06", "info",
                                        f"Хэт өндөр утга (медиан {med:g}); устгаагүй, тэмдэглэв",
                                        pid, bid, r.day, original_value=f"{r.sales_qty:g}"))

    # DQ-07 — бүтээгдэхүүний код солигдсон сэжиг: нэг салбарт нэг цуваа дуусч,
    # 14 хоногийн дотор шинэ цуваа ижил түвшнээр эхэлсэн
    if daily.empty:
        return issues
    global_start = daily["day"].min()
    by_branch: dict[str, list] = {}
    for (pid, bid), (start, last_sale, n_days, mean_pos) in spans.items():
        by_branch.setdefault(bid, []).append((pid, start, last_sale, n_days, mean_pos))
    for bid, items in by_branch.items():
        ended = [i for i in items if pd.notna(i[2]) and i[3] >= 60]
        started = [i for i in items if (i[1] - global_start).days > 30]
        for a in ended:
            for b in started:
                if a[0] == b[0] or pd.isna(a[4]) or pd.isna(b[4]):
                    continue
                gap = (b[1] - a[2]).days
                if 0 <= gap <= 14 and 0.5 <= (b[4] / a[4]) <= 2.0:
                    issues.append(Issue("DQ-07", "warning",
                                        f"Код солигдсон байж магадгүй: {a[0]} {a[2].date()}-нд дууссан, "
                                        f"{b[0]} {b[1].date()}-нд эхэлсэн (ижил түвшин)",
                                        b[0], bid, b[1].date(), original_value=f"{a[0]}->{b[0]}"))
    return issues


def apply_resolutions(tx: pd.DataFrame, resolutions: list[dict]) -> tuple[pd.DataFrame, set[int]]:
    """Хэрэглэгчийн шийдвэрийг (FR-D6) анхны мөрийг өөрчлөхгүйгээр хэрэглэнэ:
    excluded → мөрийг цуваанаас хасна; corrected → залруулсан утгыг ашиглана
    (DQ-01: хэмжээ, DQ-02: огноо). Буцаах: (залруулсан хуулбар, хасах мөрүүд)."""
    out = tx.copy()
    drop: set[int] = set()
    for r in resolutions:
        row = r.get("source_row")
        if row is None:
            continue
        if r["action"] == "excluded":
            drop.add(int(row))
        elif r["action"] == "corrected":
            mask = out["source_row"] == int(row)
            if r["rule_id"] == "DQ-01":
                out.loc[mask, "qty"] = float(r["corrected_value"])
            elif r["rule_id"] == "DQ-02":
                out.loc[mask, "txn_date"] = pd.Timestamp(r["corrected_value"])
    return out, drop
