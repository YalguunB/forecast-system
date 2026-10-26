"""worker — jobs хүснэгтээс ажил авч гүйцэтгэнэ (A1, A2, FR-M5).

Ажил авах SQL нь §4.5-ынхтай ижил: FOR UPDATE SKIP LOCKED нь хоёр worker нэг ажлыг
авахаас сэргийлнэ. Handler бүр өөрийн гүйлгээнд ажиллана; алдаа гарвал бүх бичилт
буцаагдаж, ажил 'failed' болно (анхны мөрийг хагас бичихгүй).

Ажиллуулах:  python -m fcsys.engine.worker
"""
from __future__ import annotations

import logging
import os
import socket
import time
import traceback

import psycopg
from psycopg.rows import dict_row

from ..config import get_settings
from .jobs import HANDLERS, WAITING, JobCancelled, JobError, maybe_finalize

log = logging.getLogger("fcsys.worker")

CLAIM_SQL = """
UPDATE governance.job
   SET status = 'running', locked_by = %(me)s,
       started_at = now(), attempts = attempts + 1
 WHERE id = (SELECT id FROM governance.job
              WHERE status = 'queued' AND NOT cancel_requested
              ORDER BY (type = 'finalize') DESC, id
              FOR UPDATE SKIP LOCKED
              LIMIT 1)
RETURNING *;
"""


def claim(conn: psycopg.Connection, me: str) -> dict | None:
    with conn.transaction():
        return conn.execute(CLAIM_SQL, {"me": me}).fetchone()


def run_one(url: str, me: str) -> bool:
    """Нэг ажил авч гүйцэтгэнэ. Ажил байсан эсэхийг буцаана."""
    with psycopg.connect(url, row_factory=dict_row, autocommit=True) as ctl:
        job = claim(ctl, me)
        if job is None:
            return False
        log.info("job %s (%s) эхэллээ", job["id"], job["type"])
        status, error, outcome = "done", None, None
        try:
            with psycopg.connect(url, row_factory=dict_row) as work:
                with work.transaction():
                    outcome = HANDLERS[job["type"]](work, job, url)
        except JobCancelled:
            status, error = "cancelled", "Хэрэглэгч цуцалсан"
        except JobError as exc:
            status, error = "failed", str(exc)
        except Exception as exc:  # noqa: BLE001
            status, error = "failed", f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=5)}"[:4000]
            log.exception("job %s бүтэлгүйтэв", job["id"])

        with ctl.transaction():
            if outcome == WAITING and status == "done":
                pass                              # эцэг ажил: хүүхдүүдийг хүлээнэ
            elif job["type"] == "finalize" and status == "done":
                ctl.execute("UPDATE governance.job SET status='done', finished_at=now() WHERE id=%s", (job["id"],))
            else:
                ctl.execute("UPDATE governance.job SET status=%s, finished_at=now(), error=%s WHERE id=%s",
                            (status, error, job["id"]))
            if job["type"] == "finalize" and status != "done":
                ctl.execute("UPDATE governance.job SET status='failed', finished_at=now(), error=%s WHERE id=%s",
                            (f"finalize: {error}", job["parent_id"]))
            if job["type"] == "forecast_batch" and job["parent_id"]:
                maybe_finalize(ctl, job["parent_id"])
        log.info("job %s → %s", job["id"], "waiting" if outcome == WAITING else status)
        return True


def drain(url: str | None = None, me: str = "inline", max_jobs: int = 10_000) -> int:
    """Дараалал хоосортол ажиллуулна (тест, нэг удаагийн ажиллагаанд)."""
    url = url or get_settings().database_url
    n = 0
    while n < max_jobs and run_one(url, me):
        n += 1
    return n


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    url = get_settings().database_url
    me = f"{socket.gethostname()}:{os.getpid()}"
    idle = float(os.environ.get("WORKER_POLL_SECONDS", "1.0"))
    log.info("worker %s эхэллээ", me)
    while True:
        try:
            if not run_one(url, me):
                time.sleep(idle)
        except psycopg.OperationalError:
            log.exception("өгөгдлийн сантай холбогдож чадсангүй; 5 сек хүлээнэ")
            time.sleep(5)


if __name__ == "__main__":
    main()
