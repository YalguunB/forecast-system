-- §4.7, NFR-3: API ба worker нь fc_app хэрэглэгчээр холбогдоно. fc_app хүснэгтийн
-- эзэн биш тул ALTER TABLE ... DISABLE TRIGGER, DROP, схем өөрчлөх эрхгүй.
-- Зөвхөн нэмэгдэх хүснэгтэд UPDATE/DELETE эрхийг огт өгөхгүй (trigger-ийн нэмэлт хамгаалалт).

GRANT USAGE ON SCHEMA raw, curated, experiment, forecast, governance TO fc_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA raw, curated, experiment, forecast, governance TO fc_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA raw, curated, experiment, forecast, governance TO fc_app;

REVOKE UPDATE, DELETE ON raw.raw_transaction            FROM fc_app;
REVOKE UPDATE, DELETE ON governance.audit_log           FROM fc_app;
REVOKE UPDATE, DELETE ON governance.forecast_adjustment FROM fc_app;
REVOKE DELETE         ON experiment.experiment          FROM fc_app;
REVOKE DELETE         ON curated.data_quality_issue     FROM fc_app;
REVOKE UPDATE, DELETE ON raw.dataset_version            FROM fc_app;
GRANT  UPDATE (row_count, date_min, date_max, status, archived_at) ON raw.dataset_version TO fc_app;
REVOKE INSERT, UPDATE, DELETE ON curated.holiday        FROM fc_app;
