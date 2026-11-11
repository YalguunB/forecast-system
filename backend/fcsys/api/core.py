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

ROLES = ("executive", "manager", "admin")

# Дипломын Хүснэгт 2.1 — үйлдэл → эрхтэй үүрэг.
# Менежерийн хандалт нь нэмээд салбараар хязгаарлагдана (branch_scope, FR-07, NFR-07).
PERMISSIONS: dict[str, tuple[str, ...]] = {
    "import":          ("manager",),
    "quality_view":    ("executive", "manager"),
    "forecast_view":   ("executive", "manager"),
    "adjust":          ("manager",),
    "export":          ("executive", "manager"),
    "experiment":      ("manager",),
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
    """Хүсэлт бүрийн холболт. Заавал Depends(get_conn, scope="function")-оор ашиглана: commit нь хариу
    илгээхээс ӨМНӨ хийгдэнэ. Анхдагч scope-д commit хариуны дараа хийгддэг тул ачаалал ихтэй үед клиентийн
    дараагийн хүсэлт (жишээ нь шинэ туршилтын validate, шинэ ажлын төлөв) мөрийг олохгүй 404 авдаг байв."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def current_user(token: str = Depends(oauth2), conn: psycopg.Connection = Depends(get_conn, scope="function")) -> dict:
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "unauthenticated", "Дахин нэвтэрнэ үү")
    user = conn.execute("SELECT id, username, full_name, roles, branches, is_active FROM governance.app_user WHERE id=%s",
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


def branch_scope(user: dict) -> list[str] | None:
    """None = бүх салбар (удирдлага, админ эсвэл '*' оноогдсон менежер); жагсаалт = зөвхөн эдгээр салбар."""
    roles = set(user["roles"])
    if "executive" in roles or "admin" in roles:
        return None
    branches = list(user.get("branches") or [])
    if "*" in branches:
        return None
    return branches


def assert_branch(user: dict, branch_id: str) -> None:
    scope = branch_scope(user)
    if scope is not None and branch_id not in scope:
        raise ApiError(403, "branch_forbidden", f"«{branch_id}» салбарын мэдээлэлд хандах эрх танд алга",
                       {"your_branches": scope})


def scope_sql(user: dict, column: str = "s.branch_id") -> tuple[str, list]:
    """SQL нөхцөл ба параметр: салбараар шүүх (хязгааргүй бол хоосон)."""
    scope = branch_scope(user)
    if scope is None:
        return "", []
    return f" AND {column} = ANY(%s)", [scope]


def not_found(what: str, ident) -> ApiError:
    return ApiError(404, "not_found", f"{what} олдсонгүй", {"id": ident})


def require_monthly(e: dict) -> None:
    """Хуучин өдрийн туршилтыг шинэ (сарын) кодоор уншихгүй — 500 биш ойлгомжтой 409."""
    from ..engine.protocol import LEGACY_MESSAGE, is_monthly
    if not is_monthly(e.get("protocol")):
        raise ApiError(409, "legacy_experiment", LEGACY_MESSAGE, {"experiment_id": e.get("id")})
