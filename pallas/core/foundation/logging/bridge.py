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

# access 刷屏路径：即使 LOG_LEVEL=DEBUG，2xx 也降到 DEBUG。
_QUIET_ACCESS_PATH_MARKERS = (
    "/pallas/api/logs",
    "/health",
    "/favicon",
)

_TRANSIENT_ASGI_EXC_NAMES = (
    "ConnectTimeout",
    "ReadTimeout",
    "ConnectError",
    "ProxyError",
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


def _is_quiet_access_line(text: str) -> bool:
    """2xx 访问日志中的高频健康/推流路径。"""
    if '" 5' in text or '" 4' in text:  # 4xx/5xx 仍可见
        return False
    return any(marker in text for marker in _QUIET_ACCESS_PATH_MARKERS)


def _is_transient_asgi_failure(record: LogRecord) -> bool:
    if "Exception in ASGI application" not in (record.getMessage() or ""):
        return False
    exc_info = record.exc_info
    if not exc_info or not exc_info[0]:
        return False
    name = getattr(exc_info[0], "__name__", "") or ""
    if name in _TRANSIENT_ASGI_EXC_NAMES:
        return True
    # httpx 常包装为 httpx.ConnectTimeout，__name__ 已覆盖；再扫 cause 链
    exc = exc_info[1]
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if type(exc).__name__ in _TRANSIENT_ASGI_EXC_NAMES:
            return True
        exc = exc.__cause__ or exc.__context__
    return False


class ChannelLoguruHandler(LoguruHandler):
    """为经 stdlib logging 转发的日志行追加 ``[标签]`` 前缀。"""

    def emit(self, record: LogRecord) -> None:
        text = record.getMessage()
        label = _stdlib_logger_channel_label(record.name)
        if label == "服务" and any(part in text for part in _TRANSIENT_UVICORN_MESSAGES):
            record.levelno = logging.WARNING
            record.levelname = "WARNING"
        elif record.name == "uvicorn.access" and _is_quiet_access_line(text):
            record.levelno = logging.DEBUG
            record.levelname = "DEBUG"
        elif label == "服务" and _is_transient_asgi_failure(record):
            # 外呼超时已在业务侧打点；避免 uvicorn 再刷 ERROR+整栈。
            record.levelno = logging.WARNING
            record.levelname = "WARNING"
            record.exc_info = None
            record.exc_text = None
        record.msg = f"[{label}] {text}" if label else text
        record.args = ()
        super().emit(record)


def apply_stdlib_logging_channel_prefix() -> None:
    import nonebot.log as nb_log

    nb_log.LoguruHandler = ChannelLoguruHandler  # type: ignore[misc, assignment]


def configure_quiet_library_loggers() -> None:
    """启动早期压制第三方库刷屏；DEBUG/TRACE 时不压制。

    ``uvicorn.access`` 在 DEBUG 下仍允许 INFO，但 ``/logs`` ``/health`` 由
    ``ChannelLoguruHandler`` 降到 DEBUG。
    """
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
