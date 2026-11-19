"""worker — jobs хүснэгтээс ажил авч гүйцэтгэнэ (A1, A2, FR-M5).

Ажил авах SQL нь §4.5-ынхтай ижил: FOR UPDATE SKIP LOCKED нь хоёр worker нэг ажлыг
авахаас сэргийлнэ. Handler бүр өөрийн гүйлгээнд ажиллана; алдаа гарвал бүх бичилт
буцаагдаж, ажил 'failed' болно (анхны мөрийг хагас бичихгүй).

Ажиллуулах:  python -m fcsys.engine.worker            (процессын тоо: WORKER_PROCESSES, анхдагч = CPU − 1, ≤ 4)

Worker унтарвал (терминал хаагдах, компьютер унтах) түүний авсан ажил «running» хэвээр үлдэж, таамаглал
гацдаг байв. Одоо асахдаа ба сул үедээ ижил компьютер дээрх үхсэн процессын ажлыг дараалалд буцаана.
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import os
import socket
import time
import traceback

# Процесс бүр нэг цөм ашиглана: олон процесс × олон BLAS урсгал нь компьютерийг дүүргэж удаашруулдаг
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

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


def _pid_alive(pid: int) -> bool:
    """Процесс амьд эсэх (Windows дээр os.kill процессыг алдаг тул OpenProcess ашиглана)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259               # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def recover_stale(conn: psycopg.Connection, me: str) -> int:
    """Энэ компьютер дээрх үхсэн worker-ийн «running» ажлыг дахин дараалалд оруулна. Handler бүр нэг гүйлгээнд
    ажилладаг тул тасарсан ажлын бичилт буцаагдсан — дахин ажиллуулахад аюулгүй. Хүүхэд ажилтай эцэг ажил
    (хүүхдүүдээ хүлээж байгаа validate/test) хөндөгдөхгүй."""
    host = me.rsplit(":", 1)[0]
    n = 0
    rows = conn.execute(
        "SELECT j.id, j.locked_by FROM governance.job j WHERE j.status='running' AND j.locked_by LIKE %s "
        "AND NOT EXISTS (SELECT 1 FROM governance.job c WHERE c.parent_id=j.id)", (host + ":%",)).fetchall()
    for r in rows:
        pid = r["locked_by"].rsplit(":", 1)[1]
        if r["locked_by"] == me or not pid.isdigit() or _pid_alive(int(pid)):
            continue
        cur = conn.execute("UPDATE governance.job SET status='queued', locked_by=NULL, started_at=NULL, "
                           "progress = progress - 'stage' WHERE id=%s AND status='running' AND locked_by=%s",
                           (r["id"], r["locked_by"]))
        if cur.rowcount:
            n += 1
            log.warning("job %s: worker %s унтарсан тул дахин дараалалд оруулав", r["id"], r["locked_by"])
    return n


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
            if job["type"] == "import" and status in ("failed", "cancelled"):
                # Импорт бүтэлгүйтсэн хувилбар «Шалгаж байна» хэвээр үлдэхгүй, давхардлын шалгалтад тооцогдохгүй
                ctl.execute("UPDATE raw.dataset_version SET status='failed' WHERE id=%s AND status='imported'",
                            (job["payload"]["version_id"],))
        log.info("job %s → %s", job["id"], "waiting" if outcome == WAITING else status)
        return True


def drain(url: str | None = None, me: str = "inline", max_jobs: int = 10_000) -> int:
    """Дараалал хоосортол ажиллуулна (тест, нэг удаагийн ажиллагаанд)."""
    url = url or get_settings().database_url
    n = 0
    while n < max_jobs and run_one(url, me):
        n += 1
    return n


def loop(url: str) -> None:
    """Нэг процессын ажлын давталт."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    me = f"{socket.gethostname()}:{os.getpid()}"
    idle = float(os.environ.get("WORKER_POLL_SECONDS", "1.0"))
    log.info("worker %s эхэллээ", me)
    last_check = 0.0
    while True:
        try:
            if time.monotonic() - last_check > 60:          # асахдаа ба минут тутам гацсан ажил шалгана
                with psycopg.connect(url, row_factory=dict_row, autocommit=True) as c:
                    recover_stale(c, me)
                last_check = time.monotonic()
            if not run_one(url, me):
                time.sleep(idle)
        except psycopg.OperationalError:
            log.exception("өгөгдлийн сантай холбогдож чадсангүй; 5 сек хүлээнэ")
            time.sleep(5)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    url = get_settings().database_url
    n = int(os.environ.get("WORKER_PROCESSES") or max(1, min(4, (os.cpu_count() or 2) - 1)))
    if n <= 1:
        loop(url)
        return
    # Барааны багц (forecast_batch) бие биеэсээ хамааралгүй тул олон процесс зэрэг тооцно (FOR UPDATE SKIP LOCKED)
    log.info("worker: %s процесс", n)
    procs = [mp.Process(target=loop, args=(url,), daemon=True) for _ in range(n)]
    for p in procs:
        p.start()
    try:
        while True:
            for i, p in enumerate(procs):                  # унасан процессыг дахин асаана
                if not p.is_alive():
                    log.warning("worker процесс %s зогссон; дахин асаана", p.pid)
                    procs[i] = mp.Process(target=loop, args=(url,), daemon=True)
                    procs[i].start()
            time.sleep(5)
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
