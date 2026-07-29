"""NoneBot ``COMMAND_START``：发行默认含空前缀，便于中文命令无需 ``/``。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from pallas.api.config import field_help, install_hot_reload_config

# 空串 + ``/``：裸发「牛牛表情」可命中 Trie；仍兼容 ``/牛牛…``。
DEFAULT_COMMAND_START: list[str] = ["", "/"]
DEFAULT_COMMAND_START_JSON = '["", "/"]'


class CommandStartConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    command_start: list[str] = Field(
        default_factory=lambda: list(DEFAULT_COMMAND_START),
        description=field_help(
            "命令触发前缀（NoneBot COMMAND_START）",
            'JSON 数组，如 ["", "/"]；空串表示无需斜杠即可触发中文命令',
            "修改后须重启 Bot 才生效（命令 Trie 在启动加载插件时注册）",
        ),
        json_schema_extra={"label": "命令前缀"},
    )


_FIELD_TO_ENV = {"command_start": "COMMAND_START"}

_handle = install_hot_reload_config(
    CommandStartConfig,
    config_module=__name__,
    field_to_env=_FIELD_TO_ENV,
)
get_command_start_config = _handle.get
reload_command_start_config = _handle.reload
clear_command_start_config_cache = _handle.clear_cache
