"""替换 NoneBot 默认 ``LoguruHandler``：为 stdlib → loguru 的日志补充通道标签（如 ``[uvicorn]``）。

须在 ``nonebot.init()`` 之前调用 ``apply_stdlib_logging_channel_prefix()``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.log import LoguruHandler

if TYPE_CHECKING:
    from logging import LogRecord


def _stdlib_logger_channel_label(logger_name: str) -> str:
    """把 stdlib logger 名收成简短标签；``.error`` 易被误认为级别，故单独映射。"""
    name = (logger_name or "").strip()
    if name == "uvicorn.error":
        return "uvicorn"
    return name


class ChannelLoguruHandler(LoguruHandler):
    """为经 stdlib logging 转发的日志行追加 ``[标签]`` 前缀（标签不等价于日志级别）。"""

    def emit(self, record: LogRecord) -> None:
        text = record.getMessage()
        label = _stdlib_logger_channel_label(record.name)
        record.msg = f"[{label}] {text}" if label else text
        record.args = ()
        super().emit(record)


def apply_stdlib_logging_channel_prefix() -> None:
    import nonebot.log as nb_log

    nb_log.LoguruHandler = ChannelLoguruHandler  # type: ignore[misc, assignment]
