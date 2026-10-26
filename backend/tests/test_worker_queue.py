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
