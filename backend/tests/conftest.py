"""Тестийн орчин: тусдаа өгөгдлийн сан үүсгэж миграцийг fc_owner-оор, API-г fc_app-аар ажиллуулна.

Шаардлага: PostgreSQL 16 ба superuser холболт (TEST_PG_SUPER_URL, анхдагч нь local socket).
  TEST_PG_SUPER_URL=postgresql://postgres@localhost/postgres pytest
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]
SUPER = os.environ.get("TEST_PG_SUPER_URL", "postgresql://postgres@/postgres?host=/tmp")


def _url(base: str, user: str, db: str, password: str) -> str:
    # base-ийн host хэсгийг ашиглан өөр хэрэглэгч, өгөгдлийн сангийн URL үүсгэнэ
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    info = conninfo_to_dict(base)
    info.update(user=user, dbname=db, password=password)
    return make_conninfo(**info)


@pytest.fixture(scope="session")
def database():
    db = f"fc_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(SUPER, autocommit=True) as c:
        for role, pw in (("fc_owner", "owner"), ("fc_app", "app")):
            if not c.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                c.execute(f"CREATE ROLE {role} LOGIN PASSWORD '{pw}'")
        c.execute(f"CREATE DATABASE {db} OWNER fc_owner")
        c.execute(f"GRANT CONNECT ON DATABASE {db} TO fc_app")
    owner = _url(SUPER, "fc_owner", db, "owner")
    app = _url(SUPER, "fc_app", db, "app")
    with psycopg.connect(_url(SUPER, "postgres", db, ""), autocommit=True) as c:
        c.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    os.environ["DATABASE_URL"] = app
    os.environ["OWNER_DATABASE_URL"] = owner
    os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)
    os.environ["BATCH_SIZE"] = "10"
    import tempfile
    os.environ["FILE_STORE"] = tempfile.mkdtemp(prefix="fc_files_")
    from fcsys.migrate import migrate
    os.environ["MIGRATIONS_DIR"] = str(ROOT / "db" / "migrations")
    migrate(owner)
    yield {"owner": owner, "app": app, "name": db}
    with psycopg.connect(SUPER, autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")


@pytest.fixture(scope="session")
def synthetic(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_synthetic.py"), "--out", str(out), "--seed", "7",
                    "--products", "9", "--branches", "2"], check=True, capture_output=True)
    return out


@pytest.fixture()
def app_conn(database):
    from fcsys.db import connect
    c = connect(database["app"])
    c.autocommit = True
    yield c
    c.close()
