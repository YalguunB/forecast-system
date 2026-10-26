"""API-ийн нийтлэг хэсэг: холболт, нэвтрэлт, эрх, алдааны хэлбэр (§4.5, §4.7)."""
from __future__ import annotations

import datetime as dt
from typing import Iterator

import bcrypt
import jwt
import psycopg
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from ..config import get_settings
from ..db import connect

ROLES = ("data_steward", "analyst", "manager", "researcher", "admin")

# Хүснэгт 4.11 — үйлдэл → эрхтэй үүрэг
PERMISSIONS: dict[str, tuple[str, ...]] = {
    "import":          ("data_steward",),
    "quality_view":    ("data_steward", "analyst", "researcher", "admin"),
    "forecast_view":   ("data_steward", "analyst", "manager", "researcher"),
    "adjust":          ("analyst",),
    "export":          ("analyst", "manager", "researcher"),
    "experiment":      ("researcher",),
    "admin":           ("admin",),
    "series_view":     ROLES,
}

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


class ApiError(HTTPException):
    """Бүх алдаа {code, message, details} хэлбэртэй (§4.5)."""

    def __init__(self, status_code: int, code: str, message: str, details: dict | None = None):
        super().__init__(status_code=status_code, detail={"code": code, "message": message,
                                                          "details": details or {}})


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def make_token(user: dict) -> str:
    s = get_settings()
    payload = {"sub": str(user["id"]), "roles": list(user["roles"]),
               "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=s.jwt_minutes)}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def get_conn() -> Iterator[psycopg.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def current_user(token: str = Depends(oauth2), conn: psycopg.Connection = Depends(get_conn)) -> dict:
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "unauthenticated", "Нэвтрэх шаардлагатай")
    user = conn.execute("SELECT id, username, full_name, roles, is_active FROM governance.app_user WHERE id=%s",
                        (int(payload["sub"]),)).fetchone()
    if not user or not user["is_active"]:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "unauthenticated", "Хэрэглэгч идэвхгүй")
    return user


def require(permission: str):
    allowed = PERMISSIONS[permission]

    def dep(user: dict = Depends(current_user)) -> dict:
        if not set(user["roles"]) & set(allowed):
            raise ApiError(status.HTTP_403_FORBIDDEN, "forbidden",
                           "Энэ үйлдлийг хийх эрхгүй", {"required_any_of": list(allowed)})
        return user
    return dep


def audit_rejected(user_id: int, action: str, object_type: str, object_id, detail: dict) -> None:
    """Татгалзсан оролдлогыг аудитад тусдаа гүйлгээгээр бичнэ (хүсэлтийн гүйлгээ буцаагдсан ч үлдэнэ;
    UC-04 хувилбар 6а)."""
    from ..db import audit
    conn = connect()
    try:
        with conn.transaction():
            audit(conn, user_id, action, object_type, object_id, detail)
    finally:
        conn.close()


def not_found(what: str, ident) -> ApiError:
    return ApiError(404, "not_found", f"{what} олдсонгүй", {"id": ident})
