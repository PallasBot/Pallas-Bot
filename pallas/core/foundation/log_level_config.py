"""WebUI 可改的日志级别（LOG_LEVEL），保存后即时生效。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pallas.api.config import field_help, install_hot_reload_config

_VALID_LOG_LEVELS = ("TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL")


class LogLevelConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    log_level: Literal[_VALID_LOG_LEVELS] = Field(
        default="INFO",
        description=field_help(
            "运行日志级别",
            "选择最详细的级别：TRACE 最细，INFO 默认，WARNING 最省",
            "保存后立即对控制台与日志文件生效，无需重启",
        ),
        json_schema_extra={"label": "日志级别"},
    )


_FIELD_TO_ENV = {"log_level": "LOG_LEVEL"}

_handle = install_hot_reload_config(
    LogLevelConfig,
    config_module=__name__,
    field_to_env=_FIELD_TO_ENV,
)
get_log_level_config = _handle.get
reload_log_level_config = _handle.reload
clear_log_level_config_cache = _handle.clear_cache
