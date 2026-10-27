"""Ажлын handler-ууд: import, regrid, validate, test (эцэг ажил), forecast_batch, finalize.

Туршилт нь run-д, run нь цувааны багцад хуваагдаж багц бүр нэг job болно (§4.4).
Бичих үйлдэл нь (run, цуваа, хуваалт)-аар идемпотент — бүтэлгүй job-ийг дахин
ажиллуулахад давхардал үүсэхгүй. Сүүлийн хүүхэд ажил finalize ажлыг үүсгэнэ.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

from .. import __version__
from ..config import get_settings
from ..db import audit, jsonb
from . import grid, ingest, validate as dq
from .evaluate import aggregate_over_origins, make_splits, metrics_for, origins_for
from .monthly import add_months, last_complete_month, monthly_target
from .models import FitContext, make_model, run_series
from .profile import profile_series
from .protocol import canonical_hash, derive_seed
from .select import select_models
from .store import (copy_rows, load_calendar, load_daily, load_holidays, load_inventory,
                    load_transactions)


class JobCancelled(Exception):
    pass


class JobError(Exception):
    """Хэрэглэгчид ойлгомжтой алдаа (job.error-д бичигдэнэ)."""


WAITING = "waiting"   # эцэг ажил: хүүхдүүд дуустал running хэвээр


def set_progress(conn_url: str, job_id: int, **progress) -> None:
    """Ахицыг тусдаа холболтоор бичнэ (handler-ийн гүйлгээ дуусахаас өмнө харагдана)."""
    with psycopg.connect(conn_url) as c:
        c.execute("UPDATE governance.job SET progress = progress || %s WHERE id = %s",
                  (jsonb(progress), job_id))


def check_cancel(conn_url: str, job_id: int) -> None:
    with psycopg.connect(conn_url) as c:
        row = c.execute("SELECT cancel_requested FROM governance.job WHERE id = %s", (job_id,)).fetchone()
    if row and row[0]:
        raise JobCancelled()


def lib_versions() -> dict:
    import statsmodels
    return {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
            "statsmodels": statsmodels.__version__, "fcsys": __version__}


# ---------------------------------------------------------------------------
# import / regrid (UC-01, UC-02)
# ---------------------------------------------------------------------------

def _product_attr(tx: pd.DataFrame, col: str) -> dict[str, str]:
    """Бүтээгдэхүүний код → нэр / ангилал (хамгийн олон давтагдсан утга). Зураглаагүй бол хоосон."""
    if col not in tx or tx[col].isna().all():
        return {}
    t = tx.dropna(subset=[col])
    t = t[t[col].astype(str).str.strip() != ""]
    if t.empty:
        return {}
    return t.groupby("product_ext_id")[col].agg(lambda s: s.mode().iloc[0]).to_dict()


def _product_names(tx: pd.DataFrame) -> dict[str, str]:
    return _product_attr(tx, "product_name")


def _series_map(conn, dataset_id: int, daily: pd.DataFrame, names: dict | None = None,
                categories: dict | None = None) -> dict[tuple[str, str], int]:
    pairs = daily[["product_id", "branch_id", "unit"]].drop_duplicates(["product_id", "branch_id"])
    names = names or {}
    categories = categories or {}
    for r in pairs.itertuples(index=False):
        conn.execute(
            "INSERT INTO curated.series (dataset_id, product_id, branch_id, unit, product_name, product_category) "
            "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (dataset_id, product_id, branch_id) DO UPDATE "
            "SET product_name = coalesce(EXCLUDED.product_name, curated.series.product_name), "
            "    product_category = coalesce(EXCLUDED.product_category, curated.series.product_category)",
            (dataset_id, r.product_id, r.branch_id, r.unit, names.get(r.product_id), categories.get(r.product_id)))
    rows = conn.execute("SELECT id, product_id, branch_id FROM curated.series WHERE dataset_id = %s",
                        (dataset_id,)).fetchall()
    return {(r["product_id"], r["branch_id"]): r["id"] for r in rows}


def _insert_issues(conn, version_id: int, issues: list[dq.Issue], smap: dict) -> None:
    rows = []
    for i in issues:
        sid = smap.get((i.product_id, i.branch_id)) if i.product_id and i.branch_id else None
        rows.append((version_id, i.rule_id, i.severity, sid, i.day, i.source_row, i.message,
                     i.original_value))
    if rows:
        copy_rows(conn, "curated.data_quality_issue",
                  ["dataset_version_id", "rule_id", "severity", "series_id", "day", "source_row",
                   "message", "original_value"], rows)


def _write_daily(conn, version_id: int, daily: pd.DataFrame, smap: dict) -> None:
    conn.execute("DELETE FROM curated.daily_series WHERE dataset_version_id = %s", (version_id,))
    sid = [smap[(p, b)] for p, b in zip(daily["product_id"], daily["branch_id"])]
    copy_rows(conn, "curated.daily_series",
              ["dataset_version_id", "series_id", "day", "sales_qty", "returns_qty", "sales_amount",
               "day_state"],
              zip([version_id] * len(daily), sid, daily["day"], daily["sales_qty"],
                  daily["returns_qty"], daily["sales_amount"], daily["day_state"]))


def handle_import(conn, job: dict, url: str) -> None:
    p = job["payload"]
    vid = p["version_id"]
    ver = conn.execute("SELECT * FROM raw.dataset_version WHERE id = %s", (vid,)).fetchone()
    mapping = ver["mapping"]
    set_progress(url, job["id"], stage="Файл уншиж байна")
    raw = ingest.read_table(ver["stored_path"])
    tx = ingest.parse_transactions(raw, mapping["fields"], mapping.get("date_format"),
                                   mapping.get("default_branch"), mapping.get("default_unit"))
    copy_rows(conn, "raw.raw_transaction",
              ["dataset_version_id", "source_row", "txn_id", "txn_date", "txn_date_raw", "product_ext_id",
               "branch_ext_id", "qty", "unit", "amount", "is_return"],
              zip([vid] * len(tx), tx["source_row"], tx["txn_id"] if tx["txn_id"].notna().any()
                  else [None] * len(tx), tx["txn_date"], tx["txn_date_raw"], tx["product_ext_id"],
                  tx["branch_ext_id"], tx["qty"], tx["unit"], tx["amount"], tx["is_return"]))

    aux = {k: ingest.parse_aux(k, path) for k, path in (p.get("aux") or {}).items()}
    set_progress(url, job["id"], stage="Чанарын шалгалт", rows=len(tx))
    today = dt.date.fromisoformat(p.get("today") or dt.date.today().isoformat())
    res = dq.validate_transactions(tx, today, mapping.get("unit_conversions"), aux.get("price"))
    _build_and_store(conn, ver, tx, res, aux, mapping)
    audit(conn, job["created_by"], "import_done", "dataset_version", vid,
          {"rows": len(tx), "issues": len(res.issues), "blocking": res.blocking})


def _build_and_store(conn, ver: dict, tx: pd.DataFrame, res: dq.ValidationResult, aux: dict,
                     mapping: dict, regrid: bool = False, drop_rows: set[int] | None = None) -> None:
    vid = ver["id"]
    clean = tx[~tx["source_row"].isin(res.quarantined_rows | (drop_rows or set()))]
    clean = grid.convert_units(clean, mapping.get("unit_conversions"))
    valid_dates = clean["txn_date"].dropna()
    date_max = valid_dates.max() if len(valid_dates) else None
    if date_max is None:
        raise JobError("Уншигдах огноотой мөр алга — хувилбарыг ашиглах боломжгүй")
    daily = grid.build_daily(clean, date_max, aux.get("calendar"), aux.get("inventory"))
    smap = _series_map(conn, ver["dataset_id"], daily, _product_names(clean), _product_attr(clean, "product_category"))
    _write_daily(conn, vid, daily, smap)
    if not regrid:
        _insert_issues(conn, vid, res.issues, smap)
        _insert_issues(conn, vid, dq.series_level_checks(daily), smap)
        _store_aux(conn, vid, aux, smap)
    blocking_open = conn.execute(
        "SELECT count(*) AS n FROM curated.data_quality_issue WHERE dataset_version_id = %s "
        "AND severity = 'blocking' AND action = 'open'", (vid,)).fetchone()["n"]
    conn.execute(
        "UPDATE raw.dataset_version SET row_count = %s, date_min = %s, date_max = %s, status = %s "
        "WHERE id = %s",
        (len(tx), valid_dates.min().date(), date_max.date(),
         "failed" if blocking_open else "validated", vid))


def _store_aux(conn, vid: int, aux: dict, smap: dict) -> None:
    if "price" in aux:
        pr = aux["price"]
        rows = [(vid, smap[(r.product_id, r.branch_id)], r.date, r.price, r.price_kind, r.known_at)
                for r in pr.itertuples(index=False) if (r.product_id, r.branch_id) in smap
                and pd.notna(r.date) and pd.notna(r.price)]
        copy_rows(conn, "curated.price_record",
                  ["dataset_version_id", "series_id", "valid_from", "price", "price_kind", "known_at"], rows)
    if "calendar" in aux:
        cal = aux["calendar"].dropna(subset=["date"]).drop_duplicates(["branch_id", "date"])
        copy_rows(conn, "curated.calendar_day", ["dataset_version_id", "branch_id", "day", "is_open"],
                  zip([vid] * len(cal), cal["branch_id"], cal["date"], cal["is_open"]))
    if "inventory" in aux:
        inv = aux["inventory"].dropna(subset=["date"]).drop_duplicates(["product_id", "branch_id", "date"])
        rows = [(vid, smap[(r.product_id, r.branch_id)], r.date, getattr(r, "on_hand", None), r.available,
                 r.reliability or "unverified")
                for r in inv.itertuples(index=False) if (r.product_id, r.branch_id) in smap]
        copy_rows(conn, "curated.inventory_snapshot",
                  ["dataset_version_id", "series_id", "day", "on_hand", "available", "reliability"], rows)
    if "promotion" in aux:
        pm = aux["promotion"]
        rows = [(vid, smap.get((r.product_id, r.branch_id)), r.date_from, r.date_to,
                 getattr(r, "promo_kind", "promo") or "promo", r.known_at) for r in pm.itertuples(index=False)]
        copy_rows(conn, "curated.promotion",
                  ["dataset_version_id", "series_id", "day_from", "day_to", "promo_kind", "known_at"], rows)


def handle_regrid(conn, job: dict, url: str) -> None:
    """Чанарын асуудлын шийдвэрийн дараа өдрийн цувааг дахин байгуулна (анхны мөр хэвээр)."""
    vid = job["payload"]["version_id"]
    ver = conn.execute("SELECT * FROM raw.dataset_version WHERE id = %s", (vid,)).fetchone()
    tx = load_transactions(conn, vid)
    issues = conn.execute(
        "SELECT rule_id, action, source_row, corrected_value FROM curated.data_quality_issue "
        "WHERE dataset_version_id = %s AND source_row IS NOT NULL", (vid,)).fetchall()
    tx2, drop = dq.apply_resolutions(tx, [dict(r) for r in issues if r["action"] in ("excluded", "corrected")])
    corrected = {r["source_row"] for r in issues if r["action"] == "corrected"}
    quarantine = {r["source_row"] for r in issues
                  if r["rule_id"] in ("DQ-01", "DQ-02") and r["source_row"] not in corrected}
    res = dq.ValidationResult(quarantined_rows=quarantine)
    aux = {"calendar": load_calendar(conn, vid), "inventory": load_inventory(conn, vid)}
    _build_and_store(conn, ver, tx2, res, aux, ver["mapping"], regrid=True, drop_rows=drop)
    audit(conn, job["created_by"], "regrid_done", "dataset_version", vid, {"excluded_rows": len(drop)})


# ---------------------------------------------------------------------------
# Туршилт (UC-04)
# ---------------------------------------------------------------------------

def _experiment(conn, eid: int, lock: bool = False) -> dict:
    row = conn.execute("SELECT e.*, v.date_max, v.sha256 AS version_sha FROM experiment.experiment e "
                       "JOIN raw.dataset_version v ON v.id = e.dataset_version_id WHERE e.id = %s"
                       + (" FOR UPDATE OF e" if lock else ""), (eid,)).fetchone()
    if not row:
        raise JobError(f"Туршилт {eid} олдсонгүй")
    return row


def _ensure_run(conn, exp: dict, phase: str, model: dict, role: str, checksum: str) -> int:
    params = model.get("params", {})
    existing = conn.execute(
        "SELECT run_id FROM experiment.run WHERE experiment_id=%s AND phase=%s AND model=%s AND params=%s",
        (exp["id"], phase, model["name"], jsonb(params))).fetchone()
    if existing:
        conn.execute("UPDATE experiment.run SET status='running', started_at=now(), finished_at=NULL "
                     "WHERE run_id=%s", (existing["run_id"],))
        return existing["run_id"]
    return conn.execute(
        "INSERT INTO experiment.run (experiment_id, phase, role, model, feature_set, params, seed, "
        "code_version, lib_versions, input_checksum) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING run_id",
        (exp["id"], phase, role, model["name"], exp["protocol"].get("feature_set", "none"), jsonb(params),
         exp["protocol"]["seed"], f"{__version__}+{get_settings().code_version}", jsonb(lib_versions()),
         checksum)).fetchone()["run_id"]


def _enqueue_children(conn, parent: dict, batches: list[dict]) -> None:
    for b in batches:
        conn.execute("INSERT INTO governance.job (parent_id, type, payload, created_by) "
                     "VALUES (%s, 'forecast_batch', %s, %s)", (parent["id"], jsonb(b), parent["created_by"]))
    conn.execute("UPDATE governance.job SET progress = progress || %s WHERE id = %s",
                 (jsonb({"children": len(batches), "stage": "Загварууд ажиллаж байна"}), parent["id"]))


def _batched(ids: list[int], size: int) -> list[list[int]]:
    return [ids[i:i + size] for i in range(0, len(ids), size)] or []


def handle_validate(conn, job: dict, url: str) -> str:
    exp = _experiment(conn, job["payload"]["experiment_id"])
    if exp["status"] != "validating":
        raise JobError(f"Туршилтын төлөв '{exp['status']}' — validation эхлүүлэх боломжгүй")
    proto = exp["protocol"]
    last = last_complete_month(exp["date_max"])
    sp = make_splits(last, proto["val_months"], proto["test_months"], proto["train_min_months"])
    vid = exp["dataset_version_id"]
    if exp["target"] == "demand":
        has_inv = conn.execute("SELECT 1 FROM curated.inventory_snapshot WHERE dataset_version_id=%s LIMIT 1",
                               (vid,)).fetchone()
        if not has_inv:
            raise JobError("Эрэлтийн (D) зорилтод нөөцийн хүртээмжийн өгөгдөл шаардлагатай (R2, UC-08)")

    # 1. Цувааны дэд багц (FR-D9): дүрэм, seed бүртгэгдэнэ. Өдрийн цуваанаас сарын цуваа (2.1).
    set_progress(url, job["id"], stage="Сарын цуваа ба дэд багц")
    daily = load_daily(conn, vid)
    rule = proto["sample"]
    seed = int(proto["seed"])
    items, eligible = [], []
    profiles = {}
    meta = {r["id"]: r for r in conn.execute(
        "SELECT s.id, s.branch_id, s.product_category FROM curated.series s "
        "JOIN raw.dataset_version v ON v.dataset_id = s.dataset_id WHERE v.id = %s", (vid,)).fetchall()}
    monthly: dict[int, pd.Series] = {}
    longest = 0
    for sid, d in daily.items():
        info = meta.get(sid, {})
        if rule.get("branches") and info.get("branch_id") not in rule["branches"]:
            continue                                   # өөр салбарын цуваа — туршилтад огт хамаарахгүй
        y = monthly_target(d, exp["target"], exp["date_max"])
        monthly[sid] = y
        n_obs = int(y.notna().sum())
        longest = max(longest, len(y))
        reason = None
        cat = info.get("product_category") or "Ангилалгүй"
        if rule.get("categories") and cat not in rule["categories"]:
            reason = f"ангилал «{cat}» сонгогдоогүй"
        elif n_obs < rule["min_length_months"]:
            reason = f"бүтэн сар {n_obs} < {rule['min_length_months']}"
        elif y.index[0] > sp.train_start:
            reason = (f"сургалтын түүх {proto['train_min_months']} сараас богино "
                      f"(эхний бүтэн сар {y.index[0]:%Y-%m})")
        if reason is None:
            prof = profile_series(y.loc[:add_months(sp.val_start, -1)])   # FR-S2: сургалтаас л
            profiles[sid] = prof
            if rule.get("classes") and prof["class"] not in rule["classes"]:
                reason = f"ангилал {prof['class']} дүрэмд ороогүй"
            elif rule.get("max_zero_share") is not None and prof["zero_share"] > rule["max_zero_share"]:
                reason = f"тэгийн хувь {prof['zero_share']:.2f} > {rule['max_zero_share']}"
            elif prof["class"] == "no_demand":
                reason = "сургалтын хугацаанд эерэг борлуулалт алга"
        (items.append((sid, False, reason)) if reason else eligible.append(sid))
    rng = np.random.default_rng(seed)
    eligible = sorted(eligible)
    if rule.get("max_series") and len(eligible) > rule["max_series"]:
        chosen = set(rng.choice(eligible, size=rule["max_series"], replace=False).tolist())
    else:
        chosen = set(eligible)
    for sid in eligible:
        items.append((sid, sid in chosen, None if sid in chosen else f"дэд багцад сонгогдоогүй (seed {seed})"))
    if not chosen:
        need = proto["train_min_months"] + proto["val_months"] + proto["test_months"]
        raise JobError(f"Туршилтад орох цуваа алга: цуваа бүр дор хаяж {need} бүтэн сарын түүхтэй байх ёстой "
                       f"(сургалт {proto['train_min_months']} + validation {proto['val_months']} + тест "
                       f"{proto['test_months']} сар), энэ өгөгдлийн хамгийн урт цуваа {longest} бүтэн сар. "
                       f"Илүү урт хугацааны өгөгдөл оруулна уу, эсвэл сургалт/validation/тестийн хугацааг богиносгоно уу.")

    conn.execute("DELETE FROM experiment.series_sample_item WHERE sample_id IN "
                 "(SELECT id FROM experiment.series_sample WHERE experiment_id=%s)", (exp["id"],))
    conn.execute("DELETE FROM experiment.series_sample WHERE experiment_id=%s", (exp["id"],))
    sample_id = conn.execute("INSERT INTO experiment.series_sample (experiment_id, rule, seed) "
                             "VALUES (%s,%s,%s) RETURNING id", (exp["id"], jsonb(rule), seed)).fetchone()["id"]
    copy_rows(conn, "experiment.series_sample_item", ["sample_id", "series_id", "included", "exclude_reason"],
              [(sample_id, s, inc, r) for s, inc, r in items])
    conn.execute("DELETE FROM curated.series_profile WHERE experiment_id=%s", (exp["id"],))
    copy_rows(conn, "curated.series_profile",
              ["experiment_id", "series_id", "train_n_months", "n_pos", "adi", "cv2", "zero_share", "acf12",
               "seasonal_strength", "class"],
              [(exp["id"], s, *[profiles[s][k] for k in ("train_n_months", "n_pos", "adi", "cv2", "zero_share",
                                                         "acf12", "seasonal_strength", "class")])
               for s in sorted(profiles)])

    # 2. Оролтын checksum: хувилбарын sha256 + дэд багц + зорилтын утга
    h = hashlib.sha256(exp["version_sha"].encode())
    for sid in sorted(chosen):
        y = monthly[sid]
        h.update(f"{sid}:".encode() + np.nan_to_num(y.values, nan=-1.0).tobytes())
    checksum = h.hexdigest()

    # 3. Run бүр (загвар × параметр) ба цувааны багц бүр нэг ажил
    base_key = canonical_hash(proto["baseline"])
    batches = []
    size = get_settings().batch_size
    for m in proto["models"]:
        role = "baseline" if canonical_hash({"name": m["name"], "params": m.get("params", {})}) == base_key \
            else "candidate"
        rid = _ensure_run(conn, exp, "validation", m, role, checksum)
        for b in _batched(sorted(chosen), size):
            batches.append({"experiment_id": exp["id"], "run_id": rid, "split": "validation", "series_ids": b})
    _enqueue_children(conn, job, batches)
    return WAITING


def handle_test(conn, job: dict, url: str) -> str:
    exp = _experiment(conn, job["payload"]["experiment_id"])
    if exp["status"] != "locked":
        raise JobError("Тест зөвхөн сонголт түгжигдсэн (locked) үед нэг удаа ажиллана")
    proto = exp["protocol"]
    sel = conn.execute(
        "SELECT ms.series_id, ms.run_id, r.model, r.params, r.input_checksum FROM experiment.model_selection ms "
        "JOIN experiment.run r ON r.run_id = ms.run_id WHERE ms.experiment_id = %s", (exp["id"],)).fetchall()
    included = [r["series_id"] for r in conn.execute(
        "SELECT i.series_id FROM experiment.series_sample_item i JOIN experiment.series_sample s ON s.id=i.sample_id "
        "WHERE s.experiment_id=%s AND i.included ORDER BY i.series_id", (exp["id"],)).fetchall()]
    checksum = sel[0]["input_checksum"]
    variants: dict[str, dict] = {}
    for r in sel:
        key = canonical_hash({"name": r["model"], "params": r["params"]})
        variants.setdefault(key, {"name": r["model"], "params": r["params"], "series": set()})["series"].add(
            r["series_id"])
    base = proto["baseline"]
    base_key = canonical_hash({"name": base["name"], "params": base.get("params", {})})
    batches = []
    size = get_settings().batch_size
    test_series = {k: sorted(v["series"]) for k, v in variants.items()}
    test_series[base_key] = included                      # суурь загвар бүх цуваанд (FR-E2)
    for key, sids in test_series.items():
        v = variants.get(key, {"name": base["name"], "params": base.get("params", {})})
        role = "selected" if key in variants else "baseline"
        rid = _ensure_run(conn, exp, "test", v, role, checksum)
        for b in _batched(sids, size):
            batches.append({"experiment_id": exp["id"], "run_id": rid, "split": "test", "series_ids": b})
    for key, v in variants.items():                        # 9-р алхам: сүүлийн эхлэлээс таамаглал
        rid = _ensure_run(conn, exp, "live", v, "selected", checksum)
        for b in _batched(sorted(v["series"]), size):
            batches.append({"experiment_id": exp["id"], "run_id": rid, "split": "live", "series_ids": b})
    _enqueue_children(conn, job, batches)
    return WAITING


def handle_forecast_batch(conn, job: dict, url: str) -> None:
    p = job["payload"]
    exp = _experiment(conn, p["experiment_id"])
    proto = exp["protocol"]
    run = conn.execute("SELECT * FROM experiment.run WHERE run_id = %s", (p["run_id"],)).fetchone()
    split = p["split"]
    H, m = int(proto["H"]), int(proto["mase_m"])
    last = last_complete_month(exp["date_max"])
    sp = make_splits(last, proto["val_months"], proto["test_months"], proto["train_min_months"])
    step = int(proto.get("step_months", 1))
    if split == "validation":
        origins, section_end = origins_for(sp.val_start, sp.val_end, step), sp.val_end
    elif split == "test":
        origins, section_end = origins_for(sp.test_start, sp.test_end, step), sp.test_end
    else:
        origins, section_end = [last], None
    daily = load_daily(conn, exp["dataset_version_id"], p["series_ids"])
    fb = proto["fallback"]

    fc_rows, metric_rows, failures = [], [], []
    for i, sid in enumerate(p["series_ids"]):
        if i % 5 == 0:
            check_cancel(url, job["id"])
        y = monthly_target(daily[sid], exp["target"], exp["date_max"])
        seed = derive_seed(int(proto["seed"]), sid)
        for o in origins:
            ctx = FitContext(series_id=sid, origin=o, target=exp["target"], horizon=H, seed=seed)
            model = make_model(run["model"], run["params"])
            fc, err = run_series(model, y, ctx, make_model(fb["name"], fb.get("params")))
            if err:
                failures.append((run["run_id"], sid, o.date(), err, fb["name"]))
            for r in fc.itertuples(index=False):
                fc_rows.append((run["run_id"], sid, split, o.date(), int(r.h), r.target_date.date(),
                                float(r.y_hat), r.q_lo, r.q_hi))
            if split == "live":
                continue
            train = y.loc[:o].values
            actual = y.reindex(fc["target_date"]).values.astype(float)
            actual[(fc["target_date"] > section_end).values] = np.nan   # хэсгээс гадуурх сарыг ашиглахгүй
            for hz in proto["horizons"]:
                k = int(hz)
                if add_months(o, k) > section_end:
                    continue                    # k сар бүтэн ажиглагдаагүй эхлэл энэ хүрээнд орохгүй
                for mt in metrics_for(actual[:k], fc["y_hat"].values[:k], train, m,
                                      fc["q_lo"].values[:k], fc["q_hi"].values[:k]):
                    metric_rows.append({"run_id": run["run_id"], "series_id": sid, "split": split,
                                        "origin_date": o.date(), "horizon": k, **mt})

    sids = list(p["series_ids"])
    conn.execute("DELETE FROM forecast.forecast_value WHERE run_id=%s AND split=%s AND series_id = ANY(%s)",
                 (run["run_id"], split, sids))
    copy_rows(conn, "forecast.forecast_value",
              ["run_id", "series_id", "split", "origin_date", "h", "target_date", "y_hat", "q_lo", "q_hi"], fc_rows)
    conn.execute("DELETE FROM forecast.run_failure WHERE run_id=%s AND series_id = ANY(%s) AND origin_date = ANY(%s)",
                 (run["run_id"], sids, [o.date() for o in origins]))
    if failures:
        copy_rows(conn, "forecast.run_failure", ["run_id", "series_id", "origin_date", "reason", "fallback_model"],
                  failures)
    if split != "live":
        conn.execute("DELETE FROM forecast.error_metric WHERE run_id=%s AND split=%s AND series_id = ANY(%s)",
                     (run["run_id"], split, sids))
        mdf = pd.DataFrame(metric_rows)
        if mdf.empty:
            return
        agg = aggregate_over_origins(mdf)
        all_rows = pd.concat([mdf, agg], ignore_index=True)
        copy_rows(conn, "forecast.error_metric",
                  ["run_id", "series_id", "split", "origin_date", "horizon", "metric", "value", "n_pairs",
                   "undefined_reason"],
                  all_rows[["run_id", "series_id", "split", "origin_date", "horizon", "metric", "value", "n_pairs",
                            "undefined_reason"]].itertuples(index=False, name=None))


def maybe_finalize(conn, parent_id: int) -> int | None:
    """Бүх хүүхэд дууссан бол finalize ажил нэг удаа үүсгэнэ (эцэг мөрийг түгжинэ)."""
    parent = conn.execute("SELECT * FROM governance.job WHERE id=%s FOR UPDATE", (parent_id,)).fetchone()
    if parent is None or parent["progress"].get("finalize_job") or parent["status"] != "running":
        return None
    left = conn.execute("SELECT count(*) AS n FROM governance.job WHERE parent_id=%s AND type='forecast_batch' "
                        "AND status IN ('queued','running')", (parent_id,)).fetchone()["n"]
    if left:
        return None
    fid = conn.execute("INSERT INTO governance.job (parent_id, type, payload, created_by) "
                       "VALUES (%s, 'finalize', %s, %s) RETURNING id",
                       (parent_id, jsonb({"parent_id": parent_id}), parent["created_by"])).fetchone()["id"]
    conn.execute("UPDATE governance.job SET progress = progress || %s WHERE id=%s",
                 (jsonb({"finalize_job": fid, "stage": "Үр дүнг нэгтгэж байна"}), parent_id))
    return fid


def handle_finalize(conn, job: dict, url: str) -> None:
    parent = conn.execute("SELECT * FROM governance.job WHERE id=%s FOR UPDATE",
                          (job["payload"]["parent_id"],)).fetchone()
    eid = parent["payload"]["experiment_id"]
    exp = _experiment(conn, eid, lock=True)
    kids = conn.execute("SELECT status, count(*) AS n FROM governance.job WHERE parent_id=%s "
                        "AND type='forecast_batch' GROUP BY status", (parent["id"],)).fetchall()
    counts = {k["status"]: k["n"] for k in kids}
    phases = ("validation",) if parent["type"] == "validate" else ("test", "live")
    run_ids = [r["run_id"] for r in conn.execute(
        "SELECT run_id FROM experiment.run WHERE experiment_id=%s AND phase = ANY(%s)", (eid, list(phases))).fetchall()]
    if counts.get("failed") or counts.get("cancelled"):
        final = "cancelled" if counts.get("cancelled") and not counts.get("failed") else "failed"
        conn.execute("UPDATE experiment.run SET status=%s, finished_at=now() WHERE run_id = ANY(%s)",
                     (final, run_ids))
        conn.execute("UPDATE governance.job SET status=%s, finished_at=now(), error=%s WHERE id=%s",
                     (final, f"Багц ажил: {counts}", parent["id"]))
        return

    conn.execute("UPDATE experiment.run SET status='done', finished_at=now(), "
                 "runtime_ms = (extract(epoch FROM now() - started_at) * 1000)::bigint WHERE run_id = ANY(%s)",
                 (run_ids,))
    if parent["type"] == "validate":
        proto = exp["protocol"]
        rows = conn.execute("SELECT run_id, series_id, horizon, metric, value, origin_date FROM forecast.error_metric "
                            "WHERE split='validation' AND run_id = ANY(%s) AND metric=%s",
                            (run_ids, proto["selection_metric"])).fetchall()
        metrics = pd.DataFrame(rows, columns=["run_id", "series_id", "horizon", "metric", "value", "origin_date"])
        metrics["value"] = pd.to_numeric(metrics["value"], errors="coerce").astype(float)
        prof = pd.DataFrame(conn.execute("SELECT series_id, class FROM curated.series_profile WHERE experiment_id=%s",
                                         (eid,)).fetchall(), columns=["series_id", "class"])
        runs = conn.execute("SELECT run_id, model, params, role FROM experiment.run WHERE run_id = ANY(%s)",
                            (run_ids,)).fetchall()
        rdf = pd.DataFrame(runs, columns=["run_id", "model", "params", "role"])
        rdf["label"] = rdf["model"] + rdf["params"].map(lambda p: json.dumps(p, sort_keys=True) if p else "")
        base_run = int(rdf.loc[rdf.role == "baseline", "run_id"].iloc[0])
        sel = select_models(metrics, prof, rdf, base_run, proto["selection_level"], proto["selection_metric"])
        conn.execute("DELETE FROM experiment.model_selection WHERE experiment_id=%s", (eid,))
        for r in sel.itertuples(index=False):
            conn.execute("INSERT INTO experiment.model_selection (experiment_id, series_id, horizon, run_id, rule, "
                         "selection_level, score, selected_on) VALUES (%s,%s,%s,%s,%s,%s,%s,'validation')",
                         (eid, r.series_id, r.horizon, r.run_id, r.rule, proto["selection_level"],
                          None if r.score is None or (isinstance(r.score, float) and np.isnan(r.score)) else r.score))
        conn.execute("UPDATE experiment.experiment SET status='validation_done' WHERE id=%s", (eid,))
        audit(conn, parent["created_by"], "validation_done", "experiment", eid, {"selections": len(sel)})
    else:
        conn.execute("UPDATE experiment.experiment SET status='test_done' WHERE id=%s", (eid,))
        audit(conn, parent["created_by"], "test_done", "experiment", eid, {})
    conn.execute("UPDATE governance.job SET status='done', finished_at=now(), progress = progress || %s "
                 "WHERE id=%s", (jsonb({"stage": "Дууссан"}), parent["id"]))


HANDLERS = {
    "import": handle_import,
    "regrid": handle_regrid,
    "validate": handle_validate,
    "test": handle_test,
    "forecast_batch": handle_forecast_batch,
    "finalize": handle_finalize,
}
