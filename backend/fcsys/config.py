"""Тохиргоо — бүх нууц утга орчны хувьсагчаар ирнэ, кодод хадгалагдахгүй (NFR-6)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Орчны хувьсагч {name} тохируулаагүй байна")
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _env(
        "DATABASE_URL", "postgresql://fc_app:app@localhost:5432/forecast"))
    owner_database_url: str = field(default_factory=lambda: _env(
        "OWNER_DATABASE_URL", "postgresql://fc_owner:owner@localhost:5432/forecast"))
    jwt_secret: str = field(default_factory=lambda: _env("JWT_SECRET", "dev-only-change-me"))
    jwt_minutes: int = field(default_factory=lambda: int(_env("JWT_MINUTES", "480")))
    file_store: str = field(default_factory=lambda: _env("FILE_STORE", "./filestore"))
    admin_username: str = field(default_factory=lambda: _env("ADMIN_USERNAME", "admin"))
    admin_password: str | None = field(default_factory=lambda: os.environ.get("ADMIN_PASSWORD"))
    code_version: str = field(default_factory=lambda: _env("CODE_VERSION", "dev"))
    batch_size: int = field(default_factory=lambda: int(_env("BATCH_SIZE", "25")))


def get_settings() -> Settings:
    return Settings()
