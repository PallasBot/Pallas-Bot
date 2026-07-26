"""WebUI 数据库后端配置：读取、落盘与草稿连通探测。"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import quote_plus

from pallas.core.foundation.config.repo_settings import repo_env_raw_value, upsert_env_dotenv_items
from pallas.core.foundation.db.runtime import get_db_backend, normalize_db_backend_name

_SUPPORTED = frozenset({"postgresql", "mongodb"})
_PASSWORD_LEAK_RE = re.compile(r"(password|passwd|pwd)\s*[=:]\s*\S+", re.IGNORECASE)


def _raw(key: str, default: str = "") -> str:
    value = repo_env_raw_value(key)
    if value is None:
        return default
    return str(value)


def _password_set(key: str) -> bool:
    return bool(_raw(key, "").strip())


def build_backend_config_view() -> dict[str, Any]:
    """合并后的后端配置视图；密码不回显明文。"""
    backend = normalize_db_backend_name(_raw("DB_BACKEND") or get_db_backend())
    return {
        "active_backend": normalize_db_backend_name(get_db_backend()),
        "backend": backend,
        "postgres": {
            "host": _raw("PG_HOST", "127.0.0.1"),
            "port": int(_raw("PG_PORT", "5432") or "5432"),
            "user": _raw("PG_USER", ""),
            "password": "",
            "password_set": _password_set("PG_PASSWORD"),
            "db": _raw("PG_DB", "PallasBot"),
            "auto_create_db": _raw("PG_AUTO_CREATE_DB", "false").strip().lower() in {"1", "true", "yes", "on"},
        },
        "mongo": {
            "host": _raw("MONGO_HOST", "127.0.0.1"),
            "port": int(_raw("MONGO_PORT", "27017") or "27017"),
            "user": _raw("MONGO_USER", ""),
            "password": "",
            "password_set": _password_set("MONGO_PASSWORD"),
            "db": _raw("MONGO_DB", "PallasBot"),
            "auth_source": _raw("MONGO_AUTH_SOURCE", "") or _raw("MONGO_DB", "PallasBot"),
        },
        "restart_required_hint": "保存后需重启 Bot，新后端才会生效。",
    }


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _sanitize_error(exc: BaseException) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    text = _PASSWORD_LEAK_RE.sub(r"\1=***", text)
    if len(text) > 240:
        text = text[:237] + "..."
    return text


def save_db_backend_config(payload: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """写入 webui.json env；空密码不覆盖已有值。不切换进程内连接。"""
    backend = normalize_db_backend_name(payload.get("backend"))
    if backend not in _SUPPORTED:
        raise ValueError(f"不支持的数据库后端: {backend}")

    items: dict[str, str] = {"DB_BACKEND": backend}
    if backend == "postgresql":
        pg = dict(payload.get("postgres") or {})
        host = str(pg.get("host") or "").strip() or "127.0.0.1"
        port = int(pg.get("port") or 5432)
        user = str(pg.get("user") or "").strip()
        db_name = str(pg.get("db") or "PallasBot").strip() or "PallasBot"
        if not re.match(r"^[A-Za-z0-9_\-]+$", db_name):
            raise ValueError(f"非法的 PG_DB: {db_name!r}")
        items.update({
            "PG_HOST": host,
            "PG_PORT": str(port),
            "PG_USER": user,
            "PG_DB": db_name,
            "PG_AUTO_CREATE_DB": "true" if _as_bool(pg.get("auto_create_db")) else "false",
        })
        password = str(pg.get("password") or "")
        if password.strip():
            items["PG_PASSWORD"] = password
    else:
        mongo = dict(payload.get("mongo") or {})
        host = str(mongo.get("host") or "").strip() or "127.0.0.1"
        port = int(mongo.get("port") or 27017)
        user = str(mongo.get("user") or "").strip()
        db_name = str(mongo.get("db") or "PallasBot").strip() or "PallasBot"
        auth_source = str(mongo.get("auth_source") or "").strip() or db_name
        items.update({
            "MONGO_HOST": host,
            "MONGO_PORT": str(port),
            "MONGO_USER": user,
            "MONGO_DB": db_name,
            "MONGO_AUTH_SOURCE": auth_source,
        })
        password = str(mongo.get("password") or "")
        if password.strip():
            items["MONGO_PASSWORD"] = password

    upsert_env_dotenv_items(items)
    message = "已保存，重启后生效"
    if force:
        message += "（已跳过连接测试）"
    return {
        "restart_required": True,
        "backend": backend,
        "message": message,
        "force": bool(force),
    }


async def probe_db_backend(payload: dict[str, Any]) -> dict[str, Any]:
    """用草稿参数短连探测；不改配置、不入全局池。"""
    backend = normalize_db_backend_name(payload.get("backend"))
    if backend not in _SUPPORTED:
        return {"ok": False, "latency_ms": 0, "detail": f"不支持的数据库后端: {backend}"}

    started = time.perf_counter()
    try:
        if backend == "postgresql":
            await _probe_postgres(dict(payload.get("postgres") or {}))
        else:
            await _probe_mongo(dict(payload.get("mongo") or {}))
    except Exception as exc:  # noqa: BLE001
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {"ok": False, "latency_ms": latency_ms, "detail": _sanitize_error(exc)}

    latency_ms = int((time.perf_counter() - started) * 1000)
    return {"ok": True, "latency_ms": latency_ms, "detail": "已连通"}


async def _probe_postgres(pg: dict[str, Any]) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    host = str(pg.get("host") or "").strip() or "127.0.0.1"
    port = int(pg.get("port") or 5432)
    user = str(pg.get("user") or "").strip()
    password = str(pg.get("password") or "")
    if not password.strip():
        password = _raw("PG_PASSWORD", "")
    db_name = str(pg.get("db") or "PallasBot").strip() or "PallasBot"
    if not re.match(r"^[A-Za-z0-9_\-]+$", db_name):
        raise ValueError(f"非法的 PG_DB: {db_name!r}")
    auth = f"{quote_plus(user)}:{quote_plus(password)}@" if user and password else ""
    url = f"postgresql+asyncpg://{auth}{host}:{port}/{db_name}"
    engine = create_async_engine(url, pool_pre_ping=False)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


async def _probe_mongo(mongo: dict[str, Any]) -> None:
    from pymongo import AsyncMongoClient

    host = str(mongo.get("host") or "").strip() or "127.0.0.1"
    port = int(mongo.get("port") or 27017)
    user = str(mongo.get("user") or "").strip()
    password = str(mongo.get("password") or "")
    if not password.strip():
        password = _raw("MONGO_PASSWORD", "")
    db_name = str(mongo.get("db") or "PallasBot").strip() or "PallasBot"
    auth_source = str(mongo.get("auth_source") or "").strip() or db_name
    if user and password:
        connection_string = (
            f"mongodb://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/?authSource={quote_plus(auth_source)}"
        )
    else:
        connection_string = f"mongodb://{host}:{port}"
    client = AsyncMongoClient(connection_string, serverSelectionTimeoutMS=8000)
    try:
        await client.admin.command("ping")
    finally:
        await client.close()
