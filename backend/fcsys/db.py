"""Өгөгдлийн сантай холбогдох туслах функц (psycopg 3)."""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import get_settings


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or get_settings().database_url, row_factory=dict_row)


@contextmanager
def transaction(url: str | None = None) -> Iterator[psycopg.Connection]:
    conn = connect(url)
    try:
        with conn.transaction():
            yield conn
    finally:
        conn.close()


def jsonb(value: Any) -> Jsonb:
    return Jsonb(value, dumps=lambda v: json.dumps(v, ensure_ascii=False, default=str))


def audit(conn: psycopg.Connection, user_id: int | None, action: str, object_type: str,
          object_id: Any = None, detail: dict | None = None) -> None:
    """Аудитын бүртгэл (FR-G3) — зөвхөн нэмнэ."""
    conn.execute(
        "INSERT INTO governance.audit_log (user_id, action, object_type, object_id, detail) "
        "VALUES (%s, %s, %s, %s, %s)",
        (user_id, action, object_type, None if object_id is None else str(object_id),
         jsonb(detail or {})),
    )
