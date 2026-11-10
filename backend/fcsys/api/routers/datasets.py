"""Өгөгдлийн багц, хувилбар, чанар (UC-01, UC-02; FR-D1–D10)."""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field

from ...config import get_settings
from ...db import audit, jsonb
from ...engine import ingest
from ..core import ApiError, assert_branch, branch_scope, get_conn, not_found, require, scope_sql

router = APIRouter(tags=["datasets"])


class DatasetIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    source: str = Field("organization", pattern="^(organization|open_data|synthetic)$")


@router.get("/datasets")
def list_datasets(conn=Depends(get_conn, scope="function"), user=Depends(require("series_view"))):
    return conn.execute(
        "SELECT d.*, (SELECT count(*) FROM raw.dataset_version v WHERE v.dataset_id=d.id) AS n_versions "
        "FROM raw.dataset d ORDER BY d.id DESC").fetchall()


@router.post("/datasets", status_code=201)
def create_dataset(body: DatasetIn, conn=Depends(get_conn, scope="function"), user=Depends(require("import"))):
    if conn.execute("SELECT 1 FROM raw.dataset WHERE name=%s", (body.name,)).fetchone():
        raise ApiError(409, "duplicate_name", "Ийм нэртэй өгөгдлийн багц байна")
    row = conn.execute("INSERT INTO raw.dataset (name, description, source, created_by) VALUES (%s,%s,%s,%s) "
                       "RETURNING *", (body.name, body.description, body.source, user["id"])).fetchone()
    audit(conn, user["id"], "create", "dataset", row["id"], {"name": body.name})
    return row


def _save_upload(upload: UploadFile, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    safe = Path(upload.filename or "file").name
    dest = folder / f"{uuid.uuid4().hex}_{safe}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(upload.file, f)
    return dest


@router.post("/datasets/{dataset_id}/preview")
def preview(dataset_id: int, file: UploadFile = File(...), conn=Depends(get_conn, scope="function"),
            user=Depends(require("import"))):
    """UC-01 алхам 2: эхний мөрүүдийг уншиж талбарын зураглалыг санал болгоно."""
    tmp = _save_upload(file, Path(get_settings().file_store) / "tmp")
    try:
        df = ingest.read_table(tmp, nrows=2000)   # огнооны хэлбэрийг таних түүвэр
    except Exception as exc:  # noqa: BLE001
        raise ApiError(422, "unreadable_file", "Файлыг уншиж чадсангүй (CSV эсвэл Excel байх ёстой)",
                       {"error": str(exc)[:300]})
    finally:
        tmp.unlink(missing_ok=True)
    sm = ingest.suggest_mapping(list(df.columns))
    return {"columns": list(df.columns), "suggested_mapping": sm,
            "suggested_date_format": ingest.suggest_date_format(df[sm["txn_date"]]) if sm.get("txn_date") else None,
            "required": ingest.REQUIRED_FIELDS, "optional": ingest.OPTIONAL_FIELDS,
            "rows": df.head(10).to_dict(orient="records")}


@router.post("/datasets/{dataset_id}/versions", status_code=202)
def create_version(
    dataset_id: int,
    file: UploadFile = File(...),
    mapping: str = Form(..., description='JSON: {"txn_date": "<багана>", ...}'),
    date_format: str | None = Form(None),
    default_branch: str | None = Form(None, description="branch_id зураглаагүй үед бүх мөрийн салбар (анхдагч ALL)"),
    default_unit: str | None = Form(None, description="unit зураглаагүй үед бүх мөрийн нэгж (анхдагч ширхэг)"),
    unit_conversions: str | None = Form(None, description='JSON: [{"product_id","from","to","factor"}]'),
    subset_rule: str | None = Form(None, description="Нээлттэй өгөгдлийн дэд багцын дүрэм, seed (FR-D9)"),
    force: bool = Form(False),
    price_file: UploadFile | None = File(None),
    calendar_file: UploadFile | None = File(None),
    inventory_file: UploadFile | None = File(None),
    promotion_file: UploadFile | None = File(None),
    conn=Depends(get_conn, scope="function"), user=Depends(require("import")),
):
    ds = conn.execute("SELECT * FROM raw.dataset WHERE id=%s", (dataset_id,)).fetchone()
    if not ds:
        raise not_found("Өгөгдлийн багц", dataset_id)
    try:
        fields = json.loads(mapping)
        conversions = json.loads(unit_conversions) if unit_conversions else []
        subset = json.loads(subset_rule) if subset_rule else None
    except json.JSONDecodeError as exc:
        raise ApiError(422, "invalid_json", "mapping / unit_conversions JSON буруу", {"error": str(exc)})

    store = Path(get_settings().file_store) / f"dataset_{dataset_id}"
    path = _save_upload(file, store)
    try:
        cols = list(ingest.read_table(path, nrows=5).columns)
    except Exception as exc:  # noqa: BLE001
        path.unlink(missing_ok=True)
        raise ApiError(422, "unreadable_file", "Файлыг уншиж чадсангүй", {"error": str(exc)[:300]})
    missing = ingest.missing_required(cols, fields)
    if missing:   # UC-01 хувилбар 2а / DQ-01: импорт зогсож, хувилбар үүсэхгүй
        path.unlink(missing_ok=True)
        raise ApiError(422, "missing_required_fields", "Заавал талбар дутуу: " + ", ".join(missing),
                       {"missing": missing, "columns": cols})
    scope = branch_scope(user)
    if scope is not None:   # FR-08: менежер зөвхөн өөрийн салбарын өгөгдөл импортлоно
        if fields.get("branch_id"):
            found = set(ingest.read_table(path)[fields["branch_id"]].astype(str).str.strip()) - {""}
            foreign = sorted(found - set(scope))
            if foreign:
                path.unlink(missing_ok=True)
                raise ApiError(403, "branch_forbidden",
                               f"Файлд таны хариуцаагүй салбарын мөр байна: {', '.join(foreign[:10])}",
                               {"your_branches": scope, "foreign": foreign[:50]})
        else:
            default_branch = default_branch or scope[0]
            if default_branch not in scope:
                path.unlink(missing_ok=True)
                raise ApiError(403, "branch_forbidden", f"«{default_branch}» салбар таны хариуцах салбар биш",
                               {"your_branches": scope})
    if fields.get("unit"):
        from ...engine.validate import numeric_share
        sample = ingest.read_table(path, nrows=500)[fields["unit"]]
        if numeric_share(sample) > 0.8:
            path.unlink(missing_ok=True)
            raise ApiError(422, "unit_column_numeric",
                           f"«{fields['unit']}» баганад тоон утга байна — энэ нь хэмжих нэгж биш бололтой "
                           "(жишээ нь «ширхэг», «кг»). Нэгж талбарыг «— байхгүй —» болгоно уу.",
                           {"column": fields["unit"], "sample": sample.head(5).tolist()})
    sha = ingest.sha256_file(path)
    dup = conn.execute("SELECT id, version_no FROM raw.dataset_version WHERE dataset_id=%s AND sha256=%s",
                       (dataset_id, sha)).fetchone()
    if dup and not force:   # UC-01 хувилбар 4а
        path.unlink(missing_ok=True)
        raise ApiError(409, "duplicate_checksum", f"Ижил checksum-тай хувилбар байна (v{dup['version_no']})",
                       {"version_id": dup["id"], "sha256": sha})
    aux = {}
    for kind, up in (("price", price_file), ("calendar", calendar_file), ("inventory", inventory_file),
                     ("promotion", promotion_file)):
        if up is not None and up.filename:
            aux[kind] = str(_save_upload(up, store))
    no = conn.execute("SELECT coalesce(max(version_no),0)+1 AS n FROM raw.dataset_version WHERE dataset_id=%s",
                      (dataset_id,)).fetchone()["n"]
    ver = conn.execute(
        "INSERT INTO raw.dataset_version (dataset_id, version_no, file_name, stored_path, sha256, mapping, "
        "subset_rule, imported_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id, version_no",
        (dataset_id, no, Path(file.filename or "file").name, str(path), sha,
         jsonb({"fields": {k: v for k, v in fields.items() if v}, "date_format": date_format,
                "default_branch": None if fields.get("branch_id") else (default_branch or ingest.DEFAULT_BRANCH),
                "default_unit": None if fields.get("unit") else (default_unit or ingest.DEFAULT_UNIT),
                "unit_conversions": conversions,
                "aux_files": sorted(aux)}), jsonb(subset) if subset else None, user["id"])).fetchone()
    job = conn.execute("INSERT INTO governance.job (type, payload, created_by) VALUES ('import', %s, %s) RETURNING id",
                       (jsonb({"version_id": ver["id"], "aux": aux}), user["id"])).fetchone()
    audit(conn, user["id"], "import_start", "dataset_version", ver["id"],
          {"file": file.filename, "sha256": sha, "duplicate_of": dup["id"] if dup else None})
    return {"job_id": job["id"], "version_id": ver["id"], "version_no": ver["version_no"], "sha256": sha}


@router.get("/datasets/{dataset_id}/versions")
def list_versions(dataset_id: int, conn=Depends(get_conn, scope="function"), user=Depends(require("series_view"))):
    return conn.execute(
        "SELECT v.id, v.version_no, v.file_name, v.sha256, v.imported_at, v.row_count, v.date_min, v.date_max, "
        "v.status, v.archived_at, u.username AS imported_by FROM raw.dataset_version v "
        "JOIN governance.app_user u ON u.id=v.imported_by WHERE v.dataset_id=%s ORDER BY v.version_no DESC",
        (dataset_id,)).fetchall()


@router.get("/dataset-versions")
def all_versions(conn=Depends(get_conn, scope="function"), user=Depends(require("series_view"))):
    return conn.execute(
        "SELECT v.id, v.version_no, v.status, v.date_min, v.date_max, v.row_count, v.archived_at, d.name AS dataset "
        "FROM raw.dataset_version v JOIN raw.dataset d ON d.id=v.dataset_id ORDER BY v.id DESC").fetchall()


def _version(conn, vid: int) -> dict:
    v = conn.execute("SELECT v.*, d.name AS dataset FROM raw.dataset_version v JOIN raw.dataset d "
                     "ON d.id=v.dataset_id WHERE v.id=%s", (vid,)).fetchone()
    if not v:
        raise not_found("Өгөгдлийн хувилбар", vid)
    return v


@router.get("/dataset-versions/{vid}")
def get_version(vid: int, conn=Depends(get_conn, scope="function"), user=Depends(require("series_view"))):
    v = _version(conn, vid)
    v.pop("stored_path", None)
    return v


@router.get("/dataset-versions/{vid}/quality")
def quality_report(vid: int, conn=Depends(get_conn, scope="function"), user=Depends(require("quality_view"))):
    """FR-D10: дүрмээр болон бүтээгдэхүүнээр."""
    v = _version(conn, vid)
    scope = branch_scope(user)
    by_rule = conn.execute(
        # n = асуудлын тоо; n_rows = хамаарах мөрийн тоо (DQ-05, DQ-11 нь бараа бүрт нэг асуудал, мөрийн тоо original_value-д)
        "SELECT i.rule_id, i.severity::text, i.action, count(*) AS n, "
        "sum(CASE WHEN i.rule_id IN ('DQ-05','DQ-11') AND i.original_value ~ '^[0-9]+$' THEN i.original_value::int ELSE 1 END) AS n_rows "
        "FROM curated.data_quality_issue i "
        "LEFT JOIN curated.series s ON s.id = i.series_id WHERE i.dataset_version_id=%s "
        + ("" if scope is None else "AND (i.series_id IS NULL OR s.branch_id = ANY(%s)) ") +
        "GROUP BY 1,2,3 ORDER BY 1,2,3", [vid] + ([] if scope is None else [scope])).fetchall()
    by_series = conn.execute("""
        SELECT s.id AS series_id, s.product_id, s.product_name, s.branch_id, s.unit,
               count(*) AS n_days, min(d.day) AS first_day, max(d.day) AS last_day,
               avg((d.sales_qty = 0)::int)::float AS zero_share,
               avg((d.day_state IN ('missing','unknown'))::int)::float AS incomplete_share
          FROM curated.daily_series d JOIN curated.series s ON s.id = d.series_id
         WHERE d.dataset_version_id = %s""" + scope_sql(user)[0] + """
         GROUP BY s.id ORDER BY coalesce(s.product_name, s.product_id), s.branch_id""", [vid, *scope_sql(user)[1]]).fetchall()
    states = conn.execute("SELECT series_id, day_state::text AS st, count(*) AS n FROM curated.daily_series "
                          "WHERE dataset_version_id=%s GROUP BY 1,2", (vid,)).fetchall()
    issues = conn.execute("SELECT series_id, count(*) AS n, count(*) FILTER (WHERE action='corrected') AS corrected "
                          "FROM curated.data_quality_issue WHERE dataset_version_id=%s AND series_id IS NOT NULL "
                          "GROUP BY 1", (vid,)).fetchall()
    st_map: dict[int, dict] = {}
    for r in states:
        st_map.setdefault(r["series_id"], {})[r["st"]] = r["n"]
    is_map = {r["series_id"]: r for r in issues}
    for r in by_series:
        r["states"] = st_map.get(r["series_id"], {})
        r["issues"] = is_map.get(r["series_id"], {}).get("n", 0)
        r["corrected"] = is_map.get(r["series_id"], {}).get("corrected", 0)
    blocking_open = sum(r["n"] for r in by_rule if r["severity"] == "blocking" and r["action"] == "open")
    return {"version": {"id": v["id"], "status": v["status"], "row_count": v["row_count"],
                        "date_min": v["date_min"], "date_max": v["date_max"], "dataset": v["dataset"]},
            "usable": v["status"] == "validated" and blocking_open == 0,
            "blocking_open": blocking_open, "by_rule": by_rule, "by_series": by_series}


@router.get("/dataset-versions/{vid}/issues")
def list_issues(vid: int, severity: str | None = None, rule_id: str | None = None, action: str | None = None,
                limit: int = Query(200, le=2000), offset: int = 0,
                conn=Depends(get_conn, scope="function"), user=Depends(require("import"))):
    q = ("SELECT i.*, i.severity::text AS severity, s.product_id, s.product_name, s.branch_id, u.username AS resolved_by_name "
         "FROM curated.data_quality_issue i LEFT JOIN curated.series s ON s.id=i.series_id "
         "LEFT JOIN governance.app_user u ON u.id=i.resolved_by WHERE i.dataset_version_id=%s")
    params: list = [vid]
    if branch_scope(user) is not None:
        q += " AND (i.series_id IS NULL OR s.branch_id = ANY(%s))"
        params.append(branch_scope(user))
    for col, val in (("i.severity::text", severity), ("i.rule_id", rule_id), ("i.action", action)):
        if val:
            q += f" AND {col} = %s"
            params.append(val)
    total = conn.execute(f"SELECT count(*) AS n FROM ({q}) x", params).fetchone()["n"]
    rows = conn.execute(q + " ORDER BY CASE i.severity WHEN 'blocking' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, "
                        "i.rule_id, i.id LIMIT %s OFFSET %s", params + [limit, offset]).fetchall()
    return {"total": total, "items": rows}


class IssueDecision(BaseModel):
    action: str = Field(pattern="^(accepted|corrected|excluded)$")
    reason: str = Field(min_length=3)
    corrected_value: str | None = None


def _assert_version_editable(conn, vid: int) -> None:
    used = conn.execute("SELECT id FROM experiment.experiment WHERE dataset_version_id=%s AND status<>'draft'",
                        (vid,)).fetchone()
    if used:
        raise ApiError(409, "version_in_use",
                       "Энэ хувилбарыг түгжигдсэн туршилт ашиглаж байна — шинэ хувилбар импортлоно уу",
                       {"experiment_id": used["id"]})


@router.patch("/issues/{issue_id}")
def decide_issue(issue_id: int, body: IssueDecision, conn=Depends(get_conn, scope="function"), user=Depends(require("import"))):
    """FR-D6: шалтгаан, хэрэглэгч хадгалагдана; анхны утга хэвээр (trigger)."""
    it = conn.execute("SELECT * FROM curated.data_quality_issue WHERE id=%s", (issue_id,)).fetchone()
    if not it:
        raise not_found("Чанарын асуудал", issue_id)
    _assert_version_editable(conn, it["dataset_version_id"])
    if body.action == "corrected":
        if it["rule_id"] not in ("DQ-01", "DQ-02") or it["source_row"] is None:
            raise ApiError(422, "not_correctable", "Залруулга зөвхөн мөрийн DQ-01 (хэмжээ), DQ-02 (огноо)-д")
        try:
            float(body.corrected_value) if it["rule_id"] == "DQ-01" else __import__("datetime").date.fromisoformat(
                body.corrected_value or "")
        except (TypeError, ValueError):
            raise ApiError(422, "invalid_correction", "Залруулсан утгын хэлбэр буруу (тоо эсвэл YYYY-MM-DD)")
    if body.action == "excluded" and it["source_row"] is None:
        raise ApiError(422, "not_excludable", "Мөртэй холбоогүй асуудлыг хасах боломжгүй; «accepted» сонгоно уу")
    row = conn.execute(
        "UPDATE curated.data_quality_issue SET action=%s, reason=%s, corrected_value=%s, resolved_by=%s, "
        "resolved_at=now() WHERE id=%s RETURNING *, severity::text AS severity",
        (body.action, body.reason, body.corrected_value, user["id"], issue_id)).fetchone()
    audit(conn, user["id"], "resolve_issue", "data_quality_issue", issue_id,
          {"action": body.action, "reason": body.reason, "original_value": it["original_value"],
           "corrected_value": body.corrected_value})
    return row


class BulkDecision(BaseModel):
    rule_id: str = Field(pattern=r"^DQ-(0[1-9]|1[01])$")
    action: str = Field(pattern="^(accepted|excluded)$")
    reason: str = Field(min_length=3)


@router.post("/dataset-versions/{vid}/issues/bulk")
def decide_bulk(vid: int, body: BulkDecision, conn=Depends(get_conn, scope="function"), user=Depends(require("import"))):
    """Нэг дүрмийн бүх нээлттэй асуудлыг нэг шалтгаанаар шийдэх. «excluded» нь зөвхөн мөртэй асуудалд."""
    _version(conn, vid)
    _assert_version_editable(conn, vid)
    rows = conn.execute(
        "UPDATE curated.data_quality_issue SET action=%s, reason=%s, resolved_by=%s, resolved_at=now() "
        "WHERE dataset_version_id=%s AND rule_id=%s AND action='open' "
        + ("AND source_row IS NOT NULL " if body.action == "excluded" else "") + "RETURNING id",
        (body.action, body.reason, user["id"], vid, body.rule_id)).fetchall()
    audit(conn, user["id"], "resolve_issues_bulk", "dataset_version", vid,
          {"rule_id": body.rule_id, "action": body.action, "reason": body.reason, "n": len(rows)})
    return {"updated": len(rows)}


@router.post("/dataset-versions/{vid}/apply", status_code=202)
def apply_decisions(vid: int, conn=Depends(get_conn, scope="function"), user=Depends(require("import"))):
    """UC-02: шийдвэрийг хэрэглэж өдрийн цувааг дахин байгуулна, төлвийг батлана."""
    _version(conn, vid)
    _assert_version_editable(conn, vid)
    job = conn.execute("INSERT INTO governance.job (type, payload, created_by) VALUES ('regrid', %s, %s) RETURNING id",
                       (jsonb({"version_id": vid}), user["id"])).fetchone()
    audit(conn, user["id"], "apply_decisions", "dataset_version", vid, {"job_id": job["id"]})
    return {"job_id": job["id"]}


@router.get("/dataset-versions/{vid}/series")
def list_series(vid: int, conn=Depends(get_conn, scope="function"), user=Depends(require("series_view"))):
    return conn.execute(
        "SELECT s.id, s.product_id, s.product_name, s.branch_id, s.unit, count(*) AS n_days, min(d.day) AS first_day, "
        "max(d.day) AS last_day, sum(d.sales_qty) AS total_qty, avg((d.sales_qty=0)::int)::float AS zero_share "
        "FROM curated.daily_series d JOIN curated.series s ON s.id=d.series_id WHERE d.dataset_version_id=%s "
        + scope_sql(user)[0] + " GROUP BY s.id ORDER BY coalesce(s.product_name, s.product_id), s.branch_id",
        [vid, *scope_sql(user)[1]]).fetchall()


@router.get("/dataset-versions/{vid}/series/{series_id}/days")
def series_days(vid: int, series_id: int, conn=Depends(get_conn, scope="function"), user=Depends(require("quality_view"))):
    """Өдрийн төлвийн календар (Чанарын шалгалтын дэлгэц)."""
    s = conn.execute("SELECT branch_id FROM curated.series WHERE id=%s", (series_id,)).fetchone()
    if not s:
        raise not_found("Цуваа", series_id)
    assert_branch(user, s["branch_id"])
    return conn.execute("SELECT day, sales_qty, returns_qty, day_state::text AS state FROM curated.daily_series "
                        "WHERE dataset_version_id=%s AND series_id=%s ORDER BY day", (vid, series_id)).fetchall()
