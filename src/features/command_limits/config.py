"""WebUI / .env：PALLAS_COMMAND_LIMIT_OVERRIDES JSON 覆盖默认命令冷却。"""

from __future__ import annotations

import json
import os
from threading import Lock
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from src.console.webui.field_help import field_help
from src.foundation.config.dotenv import merged_repo_dotenv_upper, repo_layered_dotenv_files_exist


class CommandLimitsConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    command_limit_overrides: dict[str, int] = Field(
        default_factory=dict,
        description=field_help(
            "覆盖各命令默认冷却秒数",
            "JSON 对象：键为命令编号，值为非负整数秒数（0 表示关闭冷却）",
            "未写的命令仍用插件默认；本页下方表格可图形化编辑",
        ),
    )

    @classmethod
    def from_env(cls) -> Self:
        merged = merged_repo_dotenv_upper()
        raw = ""
        if "PALLAS_COMMAND_LIMIT_OVERRIDES" in os.environ:
            raw = (os.environ.get("PALLAS_COMMAND_LIMIT_OVERRIDES") or "").strip()
        elif "PALLAS_COMMAND_LIMIT_OVERRIDES" in merged:
            raw = (merged.get("PALLAS_COMMAND_LIMIT_OVERRIDES") or "").strip()
        elif not repo_layered_dotenv_files_exist():
            try:
                from nonebot import get_driver

                cfg = get_driver().config
                if "pallas_command_limit_overrides" in (getattr(cfg, "model_fields_set", None) or set()):
                    v = getattr(cfg, "pallas_command_limit_overrides", None)
                    if isinstance(v, dict):
                        return cls(command_limit_overrides=normalize_command_limit_overrides(v))
                    if isinstance(v, str) and v.strip():
                        raw = v.strip()
            except ValueError:
                pass
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return cls()
        if not isinstance(data, dict):
            return cls()
        return cls(command_limit_overrides=normalize_command_limit_overrides(data))


def normalize_command_limit_overrides(raw: dict[object, object]) -> dict[str, int]:
    out: dict[str, int] = {}
    for key, value in raw.items():
        cid = str(key).strip()
        if not cid:
            continue
        try:
            cd_sec = int(value)
        except (TypeError, ValueError):
            continue
        if cd_sec < 0:
            continue
        out[cid] = cd_sec
    return out


_config_lock = Lock()
_cached: CommandLimitsConfig | None = None


def clear_command_limits_cache() -> None:
    global _cached
    with _config_lock:
        _cached = None
    try:
        from . import schema as command_limits_schema

        command_limits_schema.clear_merged_command_limits_cache()
    except Exception:
        pass


def get_command_limits_config() -> CommandLimitsConfig:
    global _cached
    with _config_lock:
        if _cached is None:
            _cached = CommandLimitsConfig.from_env()
        return _cached
