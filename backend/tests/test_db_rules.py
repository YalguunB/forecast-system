"""Өгөгдлийн сангийн дүрмийн тест (§4.9 «Өгөгдлийн сан», §4.8, NFR-2, NFR-3).

Бүх оролдлогыг API-ийн хэрэглэгч fc_app-аар хийнэ — энэ хэрэглэгч trigger-ийг тойрч чадахгүй байх ёстой.
"""
import psycopg
import pytest

from fcsys.db import jsonb


@pytest.fixture()
def base(app_conn):
    c = app_conn
    uid = c.execute("INSERT INTO governance.app_user (username, password_hash, roles) VALUES "
                    "('rules_' || md5(random()::text), 'x', '{manager}') RETURNING id").fetchone()["id"]
    ds = c.execute("INSERT INTO raw.dataset (name, created_by) VALUES ('rules_' || md5(random()::text), %s) "
                   "RETURNING id", (uid,)).fetchone()["id"]
    vid = c.execute("INSERT INTO raw.dataset_version (dataset_id, version_no, file_name, stored_path, sha256, mapping, "
                    "imported_by, status) VALUES (%s, 1, 'f.csv', '/x', 'abc', '{}', %s, 'validated') RETURNING id",
                    (ds, uid)).fetchone()["id"]
    sid = c.execute("INSERT INTO curated.series (dataset_id, product_id, branch_id, unit) VALUES (%s,'P','B','ш') "
                    "RETURNING id", (ds,)).fetchone()["id"]
    eid = c.execute("INSERT INTO experiment.experiment (name, dataset_version_id, target, protocol, created_by) "
                    "VALUES ('t', %s, 'sales', '{\"a\":1}', %s) RETURNING id", (vid, uid)).fetchone()["id"]
    return {"c": c, "uid": uid, "vid": vid, "sid": sid, "eid": eid}


def _raises(c, sql, params=(), match=None):
    with pytest.raises(psycopg.Error) as ei:
        c.execute(sql, params)
    if match:
        assert match in str(ei.value)


def test_raw_transaction_is_immutable(base):
    c = base["c"]
    rid = c.execute("INSERT INTO raw.raw_transaction (dataset_version_id, source_row, txn_date, txn_date_raw, "
                    "product_ext_id, branch_ext_id, qty, unit) VALUES (%s, 2, '2025-01-01', '2025-01-01', 'P', 'B', 1, 'ш') "
                    "RETURNING id", (base["vid"],)).fetchone()["id"]
    _raises(c, "UPDATE raw.raw_transaction SET qty = 5 WHERE id=%s", (rid,))
    _raises(c, "DELETE FROM raw.raw_transaction WHERE id=%s", (rid,))


def test_app_role_cannot_disable_triggers(base):
    _raises(base["c"], "ALTER TABLE experiment.experiment DISABLE TRIGGER experiment_lock", match="owner")
    _raises(base["c"], "ALTER TABLE raw.raw_transaction DISABLE TRIGGER ALL", match="owner")


def test_experiment_protocol_locked_after_validation_starts(base):
    c, eid = base["c"], base["eid"]
    c.execute("UPDATE experiment.experiment SET protocol='{\"a\":2}' WHERE id=%s", (eid,))          # draft: OK
    _raises(c, "UPDATE experiment.experiment SET status='validating' WHERE id=%s", (eid,))       # hash-гүй → CHECK
    c.execute("UPDATE experiment.experiment SET status='validating', protocol_hash='h1' WHERE id=%s", (eid,))
    _raises(c, "UPDATE experiment.experiment SET protocol='{\"a\":3}' WHERE id=%s", (eid,), "locked")
    _raises(c, "UPDATE experiment.experiment SET target='demand' WHERE id=%s", (eid,), "locked")
    _raises(c, "UPDATE experiment.experiment SET protocol_hash='h2' WHERE id=%s", (eid,), "immutable")
    _raises(c, "UPDATE experiment.experiment SET status='draft' WHERE id=%s", (eid,), "backwards")
    _raises(c, "UPDATE experiment.experiment SET status='locked', selection_hash='s' WHERE id=%s", (eid,), "skip")
    _raises(c, "DELETE FROM experiment.experiment WHERE id=%s", (eid,))


def test_test_run_requires_locked_and_selection_frozen(base):
    c, eid, sid = base["c"], base["eid"], base["sid"]
    run = ("INSERT INTO experiment.run (experiment_id, phase, model, feature_set, params, seed, code_version, "
           "lib_versions, input_checksum) VALUES (%s, %s, 'snaive', 'none', %s, 1, 'v', '{}', 'c') RETURNING run_id")
    _raises(c, run, (eid, "validation", jsonb({})), "validating")          # draft үед validation run хориотой
    c.execute("UPDATE experiment.experiment SET status='validating', protocol_hash='h' WHERE id=%s", (eid,))
    vrun = c.execute(run, (eid, "validation", jsonb({}))).fetchone()["run_id"]
    _raises(c, run, (eid, "test", jsonb({"x": 1})), "locked")              # validating үед тест хориотой
    sel = ("INSERT INTO experiment.model_selection (experiment_id, series_id, horizon, run_id, rule, selection_level, "
           "selected_on) VALUES (%s,%s,%s,%s,'r','global',%s)")
    _raises(c, sel, (eid, sid, 1, vrun, "test"), "selected_on")             # FR-M4: зөвхөн validation
    _raises(c, sel, (eid, sid, 7, vrun, "validation"), "horizon")           # сарын хүрээ 1, 3, 12 л
    c.execute(sel, (eid, sid, 1, vrun, "validation"))
    c.execute("UPDATE experiment.experiment SET status='validation_done' WHERE id=%s", (eid,))
    _raises(c, "UPDATE experiment.model_selection SET rule='x' WHERE experiment_id=%s", (eid,), "frozen")
    c.execute("UPDATE experiment.experiment SET status='locked', selection_hash='s' WHERE id=%s", (eid,))
    _raises(c, "UPDATE experiment.experiment SET selection_hash='s2' WHERE id=%s", (eid,), "immutable")
    c.execute(run, (eid, "test", jsonb({})))                                 # locked үед OK


def test_forecast_value_constraints(base):
    c, eid, sid = base["c"], base["eid"], base["sid"]
    c.execute("UPDATE experiment.experiment SET status='validating', protocol_hash='h' WHERE id=%s", (eid,))
    rid = c.execute("INSERT INTO experiment.run (experiment_id, phase, model, feature_set, params, seed, code_version, "
                    "lib_versions, input_checksum) VALUES (%s,'validation','naive','none','{}',1,'v','{}','c') "
                    "RETURNING run_id", (eid,)).fetchone()["run_id"]
    ins = ("INSERT INTO forecast.forecast_value (run_id, series_id, split, origin_date, h, target_date, y_hat, q_lo, q_hi) "
           "VALUES (%s,%s,%s,'2025-01-01',%s,%s,1.0,%s,%s)")
    # Сарын түвшин (006_monthly): эхлэл = сарын 1, зорилтот сар = эхлэл + h сар, h = 1..12
    c.execute(ins, (rid, sid, "validation", 1, "2025-02-01", None, None))
    _raises(c, ins, (rid, sid, "validation", 2, "2025-04-01", None, None))   # target_date ≠ o + h сар
    _raises(c, ins, (rid, sid, "validation", 13, "2026-02-01", None, None))  # h > 12
    _raises(c, ins, (rid, sid, "test", 3, "2025-04-01", None, None))         # split ≠ run.phase (FK)
    _raises(c, ins, (rid, sid, "validation", 1, "2025-02-01", None, None))   # давхардсан түлхүүр
    _raises(c, ins, (rid, sid, "validation", 4, "2025-05-01", 1.0, None))    # зөвхөн нэг хязгаар
    _raises(c, ins.replace("'2025-01-01'", "'2025-01-15'"), (rid, sid, "validation", 1, "2025-02-15", None, None))  # эхлэл сарын 1 биш
    _raises(c, "INSERT INTO forecast.error_metric (run_id, series_id, split, horizon, metric, value, n_pairs) "
               "VALUES (%s,%s,'validation',1,'MASE',NULL,5)", (rid, sid), "check")  # undefined_reason заавал
    _raises(c, "INSERT INTO forecast.error_metric (run_id, series_id, split, horizon, metric, value, n_pairs) "
               "VALUES (%s,%s,'validation',7,'MASE',1.0,5)", (rid, sid), "horizon")  # сарын хүрээ 1, 3, 12 л


def test_append_only_tables(base):
    c = base["c"]
    aid = c.execute("INSERT INTO governance.audit_log (user_id, action, object_type) VALUES (%s,'x','y') RETURNING id",
                    (base["uid"],)).fetchone()["id"]
    _raises(c, "UPDATE governance.audit_log SET action='z' WHERE id=%s", (aid,))
    _raises(c, "DELETE FROM governance.audit_log WHERE id=%s", (aid,))


def test_dq_issue_original_value_kept(base):
    c = base["c"]
    iid = c.execute("INSERT INTO curated.data_quality_issue (dataset_version_id, rule_id, severity, message, "
                    "original_value) VALUES (%s,'DQ-01','blocking','m','abc') RETURNING id", (base["vid"],)).fetchone()["id"]
    _raises(c, "UPDATE curated.data_quality_issue SET action='excluded' WHERE id=%s", (iid,), "check")  # шалтгаангүй
    c.execute("UPDATE curated.data_quality_issue SET action='corrected', corrected_value='3', reason='typo', "
              "resolved_by=%s WHERE id=%s", (base["uid"], iid))
    _raises(c, "UPDATE curated.data_quality_issue SET original_value='3' WHERE id=%s", (iid,), "immutable")
    _raises(c, "UPDATE curated.data_quality_issue SET rule_id='DQ-02' WHERE id=%s", (iid,))   # дүрмийн дугаар өөрчлөгдөхгүй
    _raises(c, "INSERT INTO curated.data_quality_issue (dataset_version_id, rule_id, severity, message) "
               "VALUES (%s,'DQ-12','info','m')", (base["vid"],), "check")                           # DQ-01–DQ-11 л
