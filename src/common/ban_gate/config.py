"""WebUI / .env：黑名单门禁内存快照。"""

from __future__ import annotations

import os
from threading import Lock
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from src.common.env_dotenv import merged_repo_dotenv_upper, repo_layered_dotenv_files_exist

_config_lock = Lock()
_cached: BanGateSnapshotConfig | None = None


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


class BanGateSnapshotConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    snapshot_refresh_sec: float = Field(
        default=30.0,
        ge=5.0,
        le=3600.0,
        description=(
            "后台全量刷新拉黑/本群屏蔽快照的间隔（秒）。"
            "默认 30；Mongo 群配置极多时可调到 45 减轻周期扫库。"
            "WebUI 保存后下一周期生效。"
        ),
    )
    snapshot_stale_sec: float = Field(
        default=120.0,
        ge=30.0,
        le=86400.0,
        description=("快照超过该秒数未刷新成功则视为过期，热路径回退短时 DB 查询。一般保持 refresh 的 2～4 倍即可。"),
    )
    gate_db_timeout_sec: float = Field(
        default=0.8,
        ge=0.1,
        le=10.0,
        description=(
            "快照未就绪或过期时，单用户/单群拉黑回退查库的超时（秒）。"
            "默认 0.8；若仍见 ban gate timeout 日志，优先加大 PG 连接池而非拉长此项。"
        ),
    )

    @classmethod
    def from_env(cls) -> Self:
        try:
            refresh = float(_env_str("PALLAS_BAN_SNAPSHOT_REFRESH_SEC", default="30") or "30")
        except ValueError:
            refresh = 30.0
        try:
            stale = float(_env_str("PALLAS_BAN_SNAPSHOT_STALE_SEC", default="120") or "120")
        except ValueError:
            stale = 120.0
        try:
            timeout = float(_env_str("PALLAS_BAN_GATE_DB_TIMEOUT_SEC", default="0.8") or "0.8")
        except ValueError:
            timeout = 0.8
        return cls(
            snapshot_refresh_sec=max(5.0, min(3600.0, refresh)),
            snapshot_stale_sec=max(30.0, min(86400.0, stale)),
            gate_db_timeout_sec=max(0.1, min(10.0, timeout)),
        )


def clear_ban_gate_snapshot_config_cache() -> None:
    global _cached
    with _config_lock:
        _cached = None


def get_ban_gate_snapshot_config() -> BanGateSnapshotConfig:
    global _cached
    with _config_lock:
        if _cached is None:
            _cached = BanGateSnapshotConfig.from_env()
        return _cached
