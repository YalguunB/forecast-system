"""Туршилт: протокол, validation, түгжилт, тест, тайлан (UC-04; FR-M1–M9, FR-X2)."""
from __future__ import annotations

import io

import psycopg
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...db import audit, jsonb
from ...engine.grid import TARGET_LABELS
from ...engine.models import MODEL_REGISTRY, PLANNED_MODELS
from ...engine.protocol import DEFAULT_PROTOCOL, ProtocolError, canonical_hash, normalize_protocol
from ...engine.report import experiment_report, report_xlsx
from ..core import ApiError, audit_rejected, get_conn, not_found, require

router = APIRouter(tags=["experiments"])


class ExperimentIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    dataset_version_id: int
    target: str = Field(pattern="^(sales|demand)$")
    protocol: dict = Field(default_factory=dict)


class ProtocolIn(BaseModel):
    protocol: dict
    target: str | None = Field(None, pattern="^(sales|demand)$")


def _exp(conn, eid: int, lock: bool = False) -> dict:
    e = conn.execute("SELECT * FROM experiment.experiment WHERE id=%s" + (" FOR UPDATE" if lock else ""),
                     (eid,)).fetchone()
    if not e:
        raise not_found("Туршилт", eid)
    e["target_label"] = TARGET_LABELS[e["target"]]
    return e


def _protocol(p: dict) -> dict:
    try:
        return normalize_protocol(p)
    except ProtocolError as exc:
        raise ApiError(422, "invalid_protocol", str(exc))


@router.get("/experiments/defaults")
def defaults(user=Depends(require("experiment"))):
    return {"protocol": DEFAULT_PROTOCOL, "models": sorted(MODEL_REGISTRY), "planned_models": PLANNED_MODELS,
            "selection_levels": ["series", "group", "global"], "targets": TARGET_LABELS}


@router.get("/experiments")
def list_experiments(conn=Depends(get_conn), user=Depends(require("forecast_view"))):
    rows = conn.execute(
        "SELECT e.id, e.name, e.target, e.status, e.dataset_version_id, e.created_at, e.locked_at, e.archived_at, "
        "u.username AS created_by, d.name AS dataset, v.version_no FROM experiment.experiment e "
        "JOIN governance.app_user u ON u.id=e.created_by JOIN raw.dataset_version v ON v.id=e.dataset_version_id "
        "JOIN raw.dataset d ON d.id=v.dataset_id ORDER BY e.id DESC").fetchall()
    for r in rows:
        r["target_label"] = TARGET_LABELS[r["target"]]
    return rows


@router.post("/experiments", status_code=201)
def create_experiment(body: ExperimentIn, conn=Depends(get_conn), user=Depends(require("experiment"))):
    v = conn.execute("SELECT status, archived_at FROM raw.dataset_version WHERE id=%s",
                     (body.dataset_version_id,)).fetchone()
    if not v:
        raise not_found("Өгөгдлийн хувилбар", body.dataset_version_id)
    if v["status"] != "validated" or v["archived_at"]:
        raise ApiError(409, "version_not_usable",
                       "Зөвхөн «шалгагдсан», архивлаагүй хувилбараар туршилт үүсгэнэ (UC-04 өмнөх нөхцөл)",
                       {"status": v["status"]})
    proto = _protocol(body.protocol)
    if body.target == "demand" and not conn.execute(
            "SELECT 1 FROM curated.inventory_snapshot WHERE dataset_version_id=%s AND reliability='reliable' LIMIT 1",
            (body.dataset_version_id,)).fetchone():
        raise ApiError(422, "demand_requires_inventory",
                       "Эрэлтийн (D) зорилтод найдвартай нөөцийн хүртээмжийн өгөгдөл шаардлагатай (R2)")
    row = conn.execute("INSERT INTO experiment.experiment (name, dataset_version_id, target, protocol, created_by) "
                       "VALUES (%s,%s,%s,%s,%s) RETURNING *",
                       (body.name, body.dataset_version_id, body.target, jsonb(proto), user["id"])).fetchone()
    audit(conn, user["id"], "create", "experiment", row["id"], {"target": body.target})
    row["target_label"] = TARGET_LABELS[row["target"]]
    return row


@router.get("/experiments/{eid}")
def get_experiment(eid: int, conn=Depends(get_conn), user=Depends(require("forecast_view"))):
    e = _exp(conn, eid)
    e["jobs"] = conn.execute("SELECT id, type, status, progress, error, created_at, finished_at FROM governance.job "
                             "WHERE parent_id IS NULL AND type IN ('validate','test') AND (payload->>'experiment_id')::bigint=%s "
                             "ORDER BY id DESC", (eid,)).fetchall()
    return e


@router.put("/experiments/{eid}/protocol")
def update_protocol(eid: int, body: ProtocolIn, conn=Depends(get_conn), user=Depends(require("experiment"))):
    e = _exp(conn, eid, lock=True)
    proto = _protocol(body.protocol)
    if e["status"] != "draft":
        audit_rejected(user["id"], "protocol_change_rejected", "experiment", eid, {"status": e["status"]})
        raise ApiError(409, "experiment_locked", "Протокол түгжигдсэн — өөрчлөх бол шинэ туршилт үүсгэнэ (UC-04 6а)",
                       {"status": e["status"]})
    row = conn.execute("UPDATE experiment.experiment SET protocol=%s, target=coalesce(%s, target) WHERE id=%s "
                       "RETURNING *", (jsonb(proto), body.target, eid)).fetchone()
    audit(conn, user["id"], "edit_protocol", "experiment", eid, {"protocol_hash_preview": canonical_hash(proto)})
    return row


@router.post("/experiments/{eid}/validate", status_code=202)
def start_validation(eid: int, conn=Depends(get_conn), user=Depends(require("experiment"))):
    """UC-04 алхам 4: протоколыг түгжиж (protocol_hash) validation ажлыг эхлүүлнэ."""
    e = _exp(conn, eid, lock=True)
    active = conn.execute("SELECT id, status FROM governance.job WHERE type='validate' AND parent_id IS NULL "
                          "AND (payload->>'experiment_id')::bigint=%s ORDER BY id DESC LIMIT 1", (eid,)).fetchone()
    if e["status"] == "draft":
        phash = canonical_hash({"target": e["target"], "dataset_version_id": e["dataset_version_id"],
                                "protocol": e["protocol"]})
        conn.execute("UPDATE experiment.experiment SET status='validating', protocol_hash=%s, protocol_locked_at=now() "
                     "WHERE id=%s", (phash, eid))
    elif e["status"] == "validating" and active and active["status"] in ("failed", "cancelled"):
        pass   # протокол аль хэдийн түгжигдсэн; бүтэлгүй ажлыг ижил протоколоор дахин ажиллуулна
    else:
        raise ApiError(409, "invalid_state", f"Validation эхлүүлэх боломжгүй (төлөв: {e['status']})",
                       {"status": e["status"]})
    job = conn.execute("INSERT INTO governance.job (type, payload, created_by) VALUES ('validate', %s, %s) RETURNING id",
                       (jsonb({"experiment_id": eid}), user["id"])).fetchone()
    audit(conn, user["id"], "lock_protocol_start_validation", "experiment", eid, {"job_id": job["id"]})
    return {"job_id": job["id"], "status": "validating"}


@router.get("/experiments/{eid}/selection")
def get_selection(eid: int, conn=Depends(get_conn), user=Depends(require("experiment"))):
    e = _exp(conn, eid)
    rows = conn.execute(
        "SELECT ms.series_id, s.product_id, s.branch_id, ms.horizon, ms.run_id, r.model, r.params, ms.rule, "
        "ms.selection_level, ms.score, p.class FROM experiment.model_selection ms "
        "JOIN experiment.run r ON r.run_id=ms.run_id JOIN curated.series s ON s.id=ms.series_id "
        "LEFT JOIN curated.series_profile p ON p.experiment_id=ms.experiment_id AND p.series_id=ms.series_id "
        "WHERE ms.experiment_id=%s ORDER BY ms.horizon, s.product_id, s.branch_id", (eid,)).fetchall()
    summary: dict = {}
    for r in rows:
        summary.setdefault(r["horizon"], {}).setdefault(r["model"], 0)
        summary[r["horizon"]][r["model"]] += 1
    return {"status": e["status"], "selection_hash": e["selection_hash"], "summary": summary, "items": rows}


@router.post("/experiments/{eid}/lock")
def lock_selection(eid: int, conn=Depends(get_conn), user=Depends(require("experiment"))):
    """UC-04 алхам 6: сонголтыг түгжинэ (selection_hash). Үүнээс хойш model_selection өөрчлөгдөхгүй."""
    e = _exp(conn, eid, lock=True)
    if e["status"] != "validation_done":
        audit_rejected(user["id"], "lock_rejected", "experiment", eid, {"status": e["status"]})
        raise ApiError(409, "invalid_state", f"Сонголтыг зөвхөн validation дууссаны дараа түгжинэ (төлөв: {e['status']})")
    sel = conn.execute("SELECT series_id, horizon, run_id, rule FROM experiment.model_selection WHERE experiment_id=%s "
                       "ORDER BY series_id, horizon", (eid,)).fetchall()
    shash = canonical_hash({"protocol_hash": e["protocol_hash"], "selection": [dict(r) for r in sel]})
    conn.execute("UPDATE experiment.experiment SET status='locked', selection_hash=%s, locked_at=now() WHERE id=%s",
                 (shash, eid))
    audit(conn, user["id"], "lock_selection", "experiment", eid, {"selection_hash": shash, "n": len(sel)})
    return {"status": "locked", "selection_hash": shash}


@router.post("/experiments/{eid}/test", status_code=202)
def run_test(eid: int, conn=Depends(get_conn), user=Depends(require("experiment"))):
    """§4.8 дүрэм 7: тест зөвхөн locked үед нэг удаа; давтан дуудахад 409."""
    e = _exp(conn, eid, lock=True)
    if e["status"] != "locked" or e["test_job_id"] is not None:
        audit_rejected(user["id"], "test_rejected", "experiment", eid,
                       {"status": e["status"], "test_job_id": e["test_job_id"]})
        raise ApiError(409, "test_already_run" if e["test_job_id"] else "invalid_state",
                       "Тест зөвхөн сонголт түгжигдсэний дараа нэг удаа ажиллана",
                       {"status": e["status"], "test_job_id": e["test_job_id"]})
    job = conn.execute("INSERT INTO governance.job (type, payload, created_by) VALUES ('test', %s, %s) RETURNING id",
                       (jsonb({"experiment_id": eid}), user["id"])).fetchone()
    try:
        conn.execute("UPDATE experiment.experiment SET test_job_id=%s WHERE id=%s", (job["id"], eid))
    except psycopg.errors.RaiseException as exc:
        raise ApiError(409, "test_already_run", str(exc).split("\n")[0])
    audit(conn, user["id"], "start_test", "experiment", eid, {"job_id": job["id"]})
    return {"job_id": job["id"]}


@router.get("/experiments/{eid}/runs")
def list_runs(eid: int, conn=Depends(get_conn), user=Depends(require("experiment"))):
    _exp(conn, eid)
    return conn.execute(
        "SELECT r.*, (SELECT count(*) FROM forecast.run_failure f WHERE f.run_id=r.run_id) AS n_failures "
        "FROM experiment.run r WHERE r.experiment_id=%s ORDER BY r.phase, r.run_id", (eid,)).fetchall()


@router.get("/experiments/{eid}/report")
def get_report(eid: int, format: str = "json", conn=Depends(get_conn), user=Depends(require("forecast_view"))):
    e = _exp(conn, eid)
    rep = experiment_report(conn, eid)
    if format == "xlsx":
        data = report_xlsx(rep)
        audit(conn, user["id"], "export_report", "experiment", eid, {})
        return StreamingResponse(io.BytesIO(data),
                                 media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                 headers={"Content-Disposition": f'attachment; filename="experiment_{eid}_report.xlsx"'})
    return rep


@router.post("/experiments/{eid}/archive")
def archive_experiment(eid: int, conn=Depends(get_conn), user=Depends(require("admin"))):
    _exp(conn, eid)
    conn.execute("UPDATE experiment.experiment SET archived_at=coalesce(archived_at, now()) WHERE id=%s", (eid,))
    audit(conn, user["id"], "archive", "experiment", eid, {})
    return {"archived": True}
