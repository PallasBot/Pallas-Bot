"""stdlib 日志转 loguru 时补通道标签。"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from nonebot.log import LoguruHandler

if TYPE_CHECKING:
    from logging import LogRecord
    from typing import Any

_TRANSIENT_UVICORN_MESSAGES = (
    "keepalive ping failed",
    "data transfer failed",
)

_CHANNEL_ALIASES = (
    ("pallas.core.", "内核"),
    ("pallas.product.", "功能"),
    ("packages.repeater.", "复读"),
    ("packages.llm_chat.", "智能对话"),
    ("packages.pb_webui.", "控制台"),
    ("packages.pb_core.", "内核插件"),
    ("packages.help.", "帮助"),
    ("uvicorn.", "服务"),
    ("celery.", "任务队列"),
    ("httpx", "HTTP"),
    ("httpcore", "HTTP"),
)

_QUIET_LIBRARY_LOGGER_NAMES = (
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
    "uvicorn.asgi",
    "celery",
    "celery.worker",
    "celery.worker.strategy",
    "celery.worker.consumer",
    "kombu",
    "amqp",
    "billiard",
    "asyncio",
    "httpx",
    "httpcore",
    "aiohttp",
    "aiohttp.access",
    "aiohttp.client",
    "aiohttp.server",
    "aiohttp.web",
    "apscheduler",
    "apscheduler.scheduler",
    "PIL",
    "PIL.PngImagePlugin",
    "urllib3",
    "urllib3.connectionpool",
    "multipart",
    "fontTools",
    "aiosqlite",
    "watchfiles",
)


def _stdlib_logger_channel_label(logger_name: str) -> str:
    """把 stdlib logger 名收成简短标签；``.error`` 易被误认为级别，故单独映射。"""
    name = (logger_name or "").strip()
    if name == "uvicorn.error":
        return "服务"
    for prefix, alias in _CHANNEL_ALIASES:
        if name == prefix.rstrip(".") or name.startswith(prefix):
            return alias
    return name


class ChannelLoguruHandler(LoguruHandler):
    """为经 stdlib logging 转发的日志行追加 ``[标签]`` 前缀。"""

    def emit(self, record: LogRecord) -> None:
        text = record.getMessage()
        label = _stdlib_logger_channel_label(record.name)
        if label == "服务" and any(part in text for part in _TRANSIENT_UVICORN_MESSAGES):
            record.levelno = logging.WARNING
            record.levelname = "WARNING"
        record.msg = f"[{label}] {text}" if label else text
        record.args = ()
        super().emit(record)


def apply_stdlib_logging_channel_prefix() -> None:
    import nonebot.log as nb_log

    nb_log.LoguruHandler = ChannelLoguruHandler  # type: ignore[misc, assignment]


def configure_quiet_library_loggers() -> None:
    """启动早期压制第三方库刷屏；DEBUG/TRACE 时不压制。"""
    level_name = resolve_repo_log_level()
    if level_name in {"TRACE", "DEBUG"}:
        return
    quiet_level = logging.WARNING
    for name in _QUIET_LIBRARY_LOGGER_NAMES:
        logging.getLogger(name).setLevel(quiet_level)


_PLUGIN_LOAD_SUCCESS_RE = re.compile(r"Succeeded to load plugin", re.IGNORECASE)
_COLOR_TAG_RE = re.compile(r"</?[a-zA-Z#][^>]*>")


def is_matcher_lifecycle_noise(plain: str) -> bool:
    """NoneBot Matcher 生命周期 INFO：每事件数行，生产 INFO 下应降为 DEBUG。"""
    text = (plain or "").strip()
    if not text:
        return False
    if text.startswith("Event will be handled by "):
        return True
    if text.endswith(" running complete") or " running is cancelled" in text:
        return True
    # 「Event foo.bar is ignored」；勿匹配 Error … Event ignored!
    if text.startswith("Event ") and text.endswith(" is ignored"):
        return True
    return False


def install_startup_log_noise_patcher() -> None:
    """在 ``nonebot.init()`` 之后调用：压制启动与 Matcher 生命周期刷屏。

    - 插件逐条 Succeeded → DEBUG（摘要已有 ``[启动] 就绪``）
    - Matcher handled / complete / cancelled / ignored → DEBUG
    """
    from nonebot import _log_patcher
    from nonebot.log import logger

    level_name = resolve_repo_log_level()
    if level_name in {"TRACE", "DEBUG"}:
        return

    debug_no = logger.level("DEBUG").no

    def patcher(record: dict[str, Any]) -> None:
        _log_patcher(record)
        plain = _COLOR_TAG_RE.sub("", str(record.get("message", "")))
        if _PLUGIN_LOAD_SUCCESS_RE.search(plain) or is_matcher_lifecycle_noise(plain):
            record["level"].name = "DEBUG"
            record["level"].no = debug_no

    logger.configure(patcher=patcher)


_VALID_LOG_LEVELS = frozenset({"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"})


def resolve_repo_log_level(*, default: str = "INFO") -> str:
    """读取 LOG_LEVEL，默认 INFO。"""
    from pallas.core.foundation.config.repo_settings import repo_env_raw_value

    raw = repo_env_raw_value("LOG_LEVEL")
    if raw is None:
        return default
    level = str(raw).strip().upper()
    if level in _VALID_LOG_LEVELS:
        return level
    return default
