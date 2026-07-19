"""数据库后端运行时：统一读取与后端类型判断。"""

from __future__ import annotations

import os

_BACKEND_ALIASES: dict[str, str] = {
    "mongo": "mongodb",
    "mongodb": "mongodb",
    "pg": "postgresql",
    "postgres": "postgresql",
    "postgresql": "postgresql",
}


def normalize_db_backend_name(raw: object, *, default: str = "postgresql") -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return default
    return _BACKEND_ALIASES.get(text, text)


def get_db_backend() -> str:
    """读取当前配置的数据库后端名称，默认为 postgresql（4.0 新装默认）。"""
    try:
        import nonebot

        backend = getattr(nonebot.get_driver().config, "db_backend", None)
        if backend:
            return normalize_db_backend_name(backend)
    except Exception:
        pass
    return normalize_db_backend_name(os.getenv("DB_BACKEND", "postgresql"))


def is_mongodb_backend(backend: str | None = None) -> bool:
    return normalize_db_backend_name(backend or get_db_backend()) == "mongodb"


def is_postgresql_backend(backend: str | None = None) -> bool:
    return normalize_db_backend_name(backend or get_db_backend()) == "postgresql"
