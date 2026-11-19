"""Ажлын дараалал (§4.5, A1): FOR UPDATE SKIP LOCKED нь хоёр worker нэг ажлыг авахаас сэргийлнэ."""
import psycopg
from psycopg.rows import dict_row

from fcsys.db import jsonb
from fcsys.engine.worker import CLAIM_SQL


def test_two_workers_claim_different_jobs(database, app_conn):
    ids = [app_conn.execute("INSERT INTO governance.job (type, payload) VALUES ('regrid', %s) RETURNING id",
                            (jsonb({"version_id": -1, "marker": "queue-test"}),)).fetchone()["id"] for _ in range(2)]
    a = psycopg.connect(database["app"], row_factory=dict_row)
    b = psycopg.connect(database["app"], row_factory=dict_row)
    try:
        ja = a.execute(CLAIM_SQL, {"me": "A"}).fetchone()        # гүйлгээ нээлттэй (түгжээ барина)
        jb = b.execute(CLAIM_SQL, {"me": "B"}).fetchone()        # А-гийн түгжсэн мөрийг алгасна
        assert ja is not None and jb is not None
        assert ja["id"] != jb["id"]
    finally:
        a.rollback(), b.rollback()
        a.close(), b.close()
    app_conn.execute("UPDATE governance.job SET status='cancelled' WHERE id = ANY(%s)", (ids,))


def test_stale_job_of_dead_worker_is_requeued(app_conn):
    """Worker унтарвал түүний «running» ажил дахин дараалалд орно; хүүхэдтэй эцэг ажил хөндөгдөхгүй."""
    import os
    from fcsys.engine.worker import recover_stale
    dead = "testhost:999999"                      # байхгүй процесс
    ins = ("INSERT INTO governance.job (type, payload, status, locked_by, started_at, parent_id) "
           "VALUES ('regrid', %s, 'running', %s, now(), %s) RETURNING id")
    lone = app_conn.execute(ins, (jsonb({"marker": "stale"}), dead, None)).fetchone()["id"]
    parent = app_conn.execute(ins, (jsonb({"marker": "stale-parent"}), dead, None)).fetchone()["id"]
    child = app_conn.execute("INSERT INTO governance.job (type, payload, parent_id) VALUES ('regrid', %s, %s) "
                             "RETURNING id", (jsonb({"marker": "stale-child"}), parent)).fetchone()["id"]
    alive = app_conn.execute(ins, (jsonb({"marker": "alive"}), f"testhost:{os.getpid()}", None)).fetchone()["id"]
    try:
        assert recover_stale(app_conn, "testhost:1") == 1
        st = {r["id"]: (r["status"], r["locked_by"]) for r in app_conn.execute(
            "SELECT id, status, locked_by FROM governance.job WHERE id = ANY(%s)", ([lone, parent, alive],)).fetchall()}
        assert st[lone] == ("queued", None)
        assert st[parent][0] == "running" and st[alive][0] == "running"
    finally:
        app_conn.execute("UPDATE governance.job SET status='cancelled' WHERE id = ANY(%s)",
                         ([lone, parent, child, alive],))
