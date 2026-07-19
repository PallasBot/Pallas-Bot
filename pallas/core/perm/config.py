"""WebUI / .env：PALLAS_COMMAND_PERMISSION_OVERRIDES JSON 覆盖默认命令权限。"""

from __future__ import annotations

import json
import os
from threading import Lock
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from pallas.console.webui.field_help import field_help
from pallas.core.foundation.config.dotenv import merged_repo_dotenv_upper, repo_layered_dotenv_files_exist


class CmdPermConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    command_permission_overrides: dict[str, str] = Field(
        default_factory=dict,
        description=field_help(
            "覆盖各命令默认的「谁可以用」",
            "JSON 对象：键为命令编号，值为权限档位（所有人、群管、号主等）",
            "未写的命令仍用插件默认；本页下方表格可图形化编辑",
        ),
    )

    @classmethod
    def from_env(cls) -> Self:
        merged = merged_repo_dotenv_upper()
        raw = ""
        if "PALLAS_COMMAND_PERMISSION_OVERRIDES" in os.environ:
            raw = (os.environ.get("PALLAS_COMMAND_PERMISSION_OVERRIDES") or "").strip()
        elif "PALLAS_COMMAND_PERMISSION_OVERRIDES" in merged:
            raw = (merged.get("PALLAS_COMMAND_PERMISSION_OVERRIDES") or "").strip()
        elif not repo_layered_dotenv_files_exist():
            try:
                from nonebot import get_driver

                cfg = get_driver().config
                if "pallas_command_permission_overrides" in (getattr(cfg, "model_fields_set", None) or set()):
                    v = getattr(cfg, "pallas_command_permission_overrides", None)
                    if isinstance(v, dict):
                        return cls(command_permission_overrides={str(k): str(val) for k, val in v.items()})
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
        return cls(command_permission_overrides={str(k): str(v) for k, v in data.items()})


_config_lock = Lock()
_cached: CmdPermConfig | None = None


def clear_cmd_perm_cache() -> None:
    global _cached
    with _config_lock:
        _cached = None
    try:
        from . import schema as cmd_perm_schema

        cmd_perm_schema.clear_merged_defaults_cache()
    except Exception:
        pass


def get_cmd_perm_config() -> CmdPermConfig:
    global _cached
    with _config_lock:
        if _cached is None:
            _cached = CmdPermConfig.from_env()
        return _cached
