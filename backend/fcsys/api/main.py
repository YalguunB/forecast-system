"""FastAPI програм (§4.5). Ажиллуулах: uvicorn fcsys.api.main:app"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import psycopg
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm

from .. import __version__
from ..config import get_settings
from ..db import audit, connect
from .core import ApiError, current_user, get_conn, hash_password, make_token, verify_password
from .routers import datasets, experiments, forecasts, governance, reports

log = logging.getLogger("fcsys.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    bootstrap_admin()
    yield


app = FastAPI(lifespan=lifespan, title="Борлуулалтын таамаглалын систем", version=__version__,
              description="Дипломын ажлын 3–4-р бүлгийн зохиомжийн хэрэгжүүлэлт", openapi_url="/api/v1/openapi.json",
              docs_url="/api/v1/docs")


@app.exception_handler(ApiError)
async def api_error(_: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status_code, content=exc.detail)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"code": "validation_error", "message": "Оролтын шалгалтад унасан",
                                                  "details": {"errors": exc.errors()}}, )


@app.exception_handler(psycopg.errors.RaiseException)
async def trigger_error(_: Request, exc: psycopg.errors.RaiseException):
    """Өгөгдлийн сангийн trigger татгалзсан (жишээ нь түгжигдсэн туршилт) → 409."""
    return JSONResponse(status_code=409, content={"code": "integrity_rule", "message": str(exc).split("\n")[0],
                                                  "details": {}})


@app.exception_handler(psycopg.errors.IntegrityError)
async def integrity_error(_: Request, exc: psycopg.errors.IntegrityError):
    return JSONResponse(status_code=409, content={"code": "integrity_rule", "message": str(exc).split("\n")[0],
                                                  "details": {"sqlstate": exc.sqlstate}})


@app.post("/api/v1/auth/token", tags=["auth"])
def login(form: OAuth2PasswordRequestForm = Depends(), conn=Depends(get_conn, scope="function")):
    user = conn.execute("SELECT * FROM governance.app_user WHERE username=%s", (form.username,)).fetchone()
    if not user or not user["is_active"] or not verify_password(form.password, user["password_hash"]):
        raise ApiError(401, "invalid_credentials", "Нэвтрэх нэр эсвэл нууц үг буруу")
    audit(conn, user["id"], "login", "app_user", user["id"], {})
    return {"access_token": make_token(user), "token_type": "bearer",
            "user": {"id": user["id"], "username": user["username"], "full_name": user["full_name"],
                     "roles": user["roles"], "branches": user["branches"]}}


@app.get("/api/v1/auth/me", tags=["auth"])
def me(user=Depends(current_user)):
    return user


@app.get("/api/v1/health", tags=["auth"])
def health(conn=Depends(get_conn, scope="function")):
    conn.execute("SELECT 1")
    return {"status": "ok", "version": __version__}


for r in (datasets.router, experiments.router, forecasts.router, governance.router, reports.router):
    app.include_router(r, prefix="/api/v1")


def bootstrap_admin() -> None:
    """Хэрэглэгч огт байхгүй үед ADMIN_PASSWORD-оор анхны админ үүсгэнэ."""
    s = get_settings()
    if not s.admin_password:
        return
    try:
        with connect() as conn:
            n = conn.execute("SELECT count(*) AS n FROM governance.app_user").fetchone()["n"]
            if n == 0:
                conn.execute("INSERT INTO governance.app_user (username, full_name, password_hash, roles) "
                             "VALUES (%s, 'Системийн админ', %s, ARRAY['admin'])",
                             (s.admin_username, hash_password(s.admin_password)))
                conn.commit()
                log.info("Анхны админ '%s' үүслээ", s.admin_username)
    except psycopg.Error:
        log.exception("Анхны админ үүсгэж чадсангүй")
