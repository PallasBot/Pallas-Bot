"""WebUI / .env：PostgreSQL 连接池与配置行缓存（仅 DB_BACKEND=postgresql 时生效）。"""

from __future__ import annotations

import os
from threading import Lock
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from src.common.env_dotenv import merged_repo_dotenv_upper, repo_layered_dotenv_files_exist

_config_lock = Lock()
_cached: PgRuntimeConfig | None = None


def _env_str(name_upper: str, *, default: str) -> str:
    merged = merged_repo_dotenv_upper()
    if name_upper in os.environ:
        return (os.environ.get(name_upper, default) or "").strip()
    if name_upper in merged:
        return (merged.get(name_upper) or "").strip()
    if not repo_layered_dotenv_files_exist():
        try:
            from nonebot import get_driver

            cfg = get_driver().config
            attr = name_upper.lower()
            if attr in (getattr(cfg, "model_fields_set", None) or set()):
                val = getattr(cfg, attr, None)
                if val is not None:
                    return str(val).strip()
        except ValueError:
            pass
    return default


class PgRuntimeConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    pool_size: int = Field(
        default=10,
        ge=1,
        le=200,
        description=(
            "SQLAlchemy 常驻连接数；高负载或多账号同进程时可酌增。"
            "与 max_overflow 之和须小于 PostgreSQL max_connections。"
            "修改后需重启 Bot。"
        ),
    )
    max_overflow: int = Field(
        default=20,
        ge=0,
        le=300,
        description=("连接池弹性上限（峰值约 pool+overflow 条连接）。高负载时可酌增。修改后需重启 Bot。"),
    )
    pool_recycle: int = Field(
        default=1800,
        ge=60,
        le=86400,
        description="空闲连接回收间隔（秒）。默认 1800。修改后需重启 Bot。",
    )
    config_cache_ttl: float = Field(
        default=60.0,
        ge=0.0,
        le=3600.0,
        description=(
            "bot_config / group_config / user_config 进程内读缓存 TTL（秒）。"
            "默认 60；减轻 help 等路径打 PG 时可酌增。0 表示禁用。WebUI 保存后立即生效。"
        ),
    )
    config_cache_size: int = Field(
        default=10000,
        ge=0,
        le=500_000,
        description="配置行缓存最大条数。WebUI 保存后立即生效。",
    )

    @classmethod
    def from_env(cls) -> Self:
        def _int(key: str, default: str, lo: int, hi: int) -> int:
            try:
                return max(lo, min(hi, int(_env_str(key, default=default) or default)))
            except ValueError:
                return int(default)

        def _float(key: str, default: str, lo: float, hi: float) -> float:
            try:
                return max(lo, min(hi, float(_env_str(key, default=default) or default)))
            except ValueError:
                return float(default)

        return cls(
            pool_size=_int("PG_POOL_SIZE", "10", 1, 200),
            max_overflow=_int("PG_MAX_OVERFLOW", "20", 0, 300),
            pool_recycle=_int("PG_POOL_RECYCLE", "1800", 60, 86400),
            config_cache_ttl=_float("PG_CONFIG_CACHE_TTL", "60", 0.0, 3600.0),
            config_cache_size=_int("PG_CONFIG_CACHE_SIZE", "10000", 0, 500_000),
        )


def clear_pg_runtime_config_cache() -> None:
    global _cached
    with _config_lock:
        _cached = None


def get_pg_runtime_config() -> PgRuntimeConfig:
    global _cached
    with _config_lock:
        if _cached is None:
            _cached = PgRuntimeConfig.from_env()
        return _cached


async def clear_pg_config_row_caches() -> None:
    """清空 ORM 配置行 TTL 缓存（WebUI 改 PG_CONFIG_CACHE_* 后调用）。"""
    from src.common.db.repository_pg import clear_pg_config_caches

    await clear_pg_config_caches()
