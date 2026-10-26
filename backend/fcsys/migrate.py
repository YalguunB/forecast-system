"""Миграци: db/migrations/*.sql-ийг дарааллаар нэг удаа ажиллуулна (fc_owner-оор).

Ажиллуулах:  python -m fcsys.migrate
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import psycopg

from .config import get_settings


def migrations_dir() -> Path:
    env = os.environ.get("MIGRATIONS_DIR")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for p in (here.parents[2] / "db" / "migrations", Path("/app/db/migrations")):
        if p.exists():
            return p
    raise SystemExit("db/migrations хавтас олдсонгүй (MIGRATIONS_DIR тохируулна уу)")


def migrate(url: str | None = None) -> list[str]:
    url = url or get_settings().owner_database_url
    applied = []
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS public.schema_migrations (name text PRIMARY KEY, sha256 text NOT NULL, "
                     "applied_at timestamptz NOT NULL DEFAULT now())")
        done = {r[0]: r[1] for r in conn.execute("SELECT name, sha256 FROM public.schema_migrations").fetchall()}
        for f in sorted(migrations_dir().glob("*.sql")):
            sql = f.read_text(encoding="utf-8")
            sha = hashlib.sha256(sql.encode()).hexdigest()
            if f.name in done:
                if done[f.name] != sha:
                    print(f"АНХААР: {f.name} ажилласны дараа өөрчлөгдсөн (шинэ миграци бичнэ үү)", file=sys.stderr)
                continue
            with conn.transaction():
                conn.execute(sql)
                conn.execute("INSERT INTO public.schema_migrations (name, sha256) VALUES (%s, %s)", (f.name, sha))
            applied.append(f.name)
            print(f"applied {f.name}")
    return applied


if __name__ == "__main__":
    migrate()
