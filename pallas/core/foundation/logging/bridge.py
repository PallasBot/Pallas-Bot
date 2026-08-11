"""stdlib 日志转 loguru 时补通道标签。"""

from __future__ import annotations

import logging
import re
import sys
from typing import TYPE_CHECKING

from nonebot.log import LoguruHandler

if TYPE_CHECKING:
    from logging import LogRecord
    from typing import Any

REPO_CONSOLE_LOG_FORMAT = (
    "<g>{time:MM-DD HH:mm:ss}</g> [<lvl>{level:<8}</lvl>] <c><u>{{{extra[display_name]:<12}}}</u></c> {message}\n"
)
REPO_FILE_LOG_FORMAT = "{time:MM-DD HH:mm:ss} [{level:<8}] {{{extra[display_name]:<12}}} {message}\n"

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
    ("uvicorn.", "HTTP 服务"),
    ("celery.", "任务队列"),
    ("httpx", "HTTP"),
    ("httpcore", "HTTP"),
)

_BUSINESS_LOG_LABELS = (
    ("packages.repeater.learn_queue", "Learn"),
    ("packages.repeater.learner", "Learn"),
    ("packages.repeater.fanout", "Reply"),
    ("packages.repeater.emoji", "Reaction"),
    ("packages.repeater", "Repeater"),
    ("packages.llm_chat", "Chat"),
    ("packages.pb_webui", "控制台"),
    ("packages.pb_core", "Core"),
    ("packages.pb_stats", "Stats"),
    ("packages.help", "Help"),
    ("packages.blacklist", "Blacklist"),
    ("packages.request_handler", "Request"),
    ("packages.take_name", "TakeName"),
    ("packages.drink", "Drink"),
    ("pallas.product.llm", "LLM"),
    ("pallas.product.persona", "Persona"),
    ("pallas.product.corpus", "Corpus"),
    ("pallas.product.message_scrub", "消息过滤"),
    ("pallas.product", "Product"),
    ("pallas.core.foundation.db", "数据库"),
    ("pallas.core.platform", "Platform"),
    ("pallas.core", "Core"),
    ("pallas.console.cli", "CLI"),
    ("pallas.console", "控制台"),
    ("pallas.extensions", "Extension"),
    ("pallas", "Pallas"),
)

_DISPLAY_LOG_NAME_PREFIXES = (
    "packages.",
    "pallas_plugin_",
    "nonebot_plugin_",
    "pallas.core",
    "pallas.product",
    "pallas.console",
    "pallas.extensions",
    "pallas",
)

_BUSINESS_EVENT_ACTIONS = {
    "复读回复": "Reply",
    "复读禁言": "Repeater ban",
    "禁言目标读取": "Ban target lookup",
    "禁言目标撤回": "Ban target recall",
    "主动发言": "Scheduled message",
    "语料回填批次": "Corpus backfill batch",
    "视觉表情跟随": "Vision sticker follow-up",
    "表情跟随投递": "Sticker follow-up delivery",
    "缓存贴纸投递": "Cached sticker delivery",
    "贴纸视觉选择": "Sticker vision selection",
    "贴纸视觉投递": "Sticker vision delivery",
    "视觉图片拉取": "Vision image fetch",
    "视觉图片理解": "Vision image analysis",
    "视觉多模态请求": "Vision multimodal request",
    "视觉文本回退": "Vision text fallback",
    "智能对话提交": "Chat submission",
}

_BUSINESS_EVENT_RESULTS = {
    "已准备": "prepared",
    "已发送": "sent",
    "已完成": "completed",
    "已跳过": "skipped",
    "已降级": "degraded",
    "已拒绝": "rejected",
    "未命中": "not matched",
    "失败": "failed",
    "发送失败": "failed to send",
    "已入队": "queued",
}

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


def display_log_name(logger_name: str) -> str:
    """返回日志中展示的短名称，不改动原始 logger name。"""
    name = (logger_name or "").strip()
    if name in {"pallas", "pallas.core"} or name.startswith("pallas.core."):
        return "Core"
    if name.startswith("packages."):
        return _pascal_case(name.split(".", 2)[1])
    for prefix in ("pallas_plugin_", "nonebot_plugin_"):
        if name.startswith(prefix):
            return _pascal_case(name.removeprefix(prefix).split(".", 1)[0])
    if name.startswith("pallas.product."):
        return _pascal_case(name.split(".", 3)[2])
    if name.startswith("pallas.console."):
        return "Console"
    if name.startswith("pallas.extensions."):
        return "Extension"
    return _pascal_case(name.split(".", 1)[0]) if name else ""


def _pascal_case(value: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[_-]+", value) if part)


def _format_repo_log(record: dict[str, Any], template: str) -> str:
    record["extra"]["display_name"] = display_log_name(str(record.get("name", "")))
    return template


def format_repo_console_log(record: dict[str, Any]) -> str:
    return _format_repo_log(record, REPO_CONSOLE_LOG_FORMAT)


def format_repo_file_log(record: dict[str, Any]) -> str:
    return _format_repo_log(record, REPO_FILE_LOG_FORMAT)


def _stdlib_logger_channel_label(logger_name: str) -> str:
    """把 stdlib logger 名收成简短标签；``.error`` 易被误认为级别，故单独映射。"""
    name = (logger_name or "").strip()
    if name == "uvicorn.error":
        return "HTTP 服务"
    for prefix, alias in _CHANNEL_ALIASES:
        if name == prefix.rstrip(".") or name.startswith(prefix):
            return alias
    return name


def prefix_business_log_message(logger_name: str, message: str) -> str:
    """为主仓业务日志补充稳定类别标签，保留调用方已有标签。"""
    text = str(message or "")
    stripped = text.lstrip()
    if not stripped or stripped.startswith("["):
        return text
    name = (logger_name or "").strip()
    for prefix, label in _BUSINESS_LOG_LABELS:
        if name == prefix or name.startswith(f"{prefix}.") or (prefix.endswith("_") and name.startswith(prefix)):
            return f"[{label}] {stripped}"
    if name.startswith(_DISPLAY_LOG_NAME_PREFIXES):
        return f"[{display_log_name(name)}] {stripped}"
    return text


def format_business_event(action: str, result: str, /, **fields: object) -> str:
    """生成单行英文结果叙事，省略空字段。"""
    if action == "复读回复" and result == "已发送":
        bot = fields.get("bot")
        group = fields.get("group")
        content = _format_business_field(fields.get("content"))
        return f"Bot {bot} replied in group {group}: {content}"

    subject = _BUSINESS_EVENT_ACTIONS.get(action, action)
    outcome = _BUSINESS_EVENT_RESULTS.get(result, result)
    text = f"{subject} {outcome}".strip()
    values = [f"{key}={_format_business_field(value)}" for key, value in fields.items() if value not in (None, "")]
    return f"{text}: {' '.join(values)}" if values else text


def _format_business_field(value: object) -> str:
    return str(value).replace("\r", "\\r").replace("\n", "\\n")


def _is_quiet_access_line(text: str) -> bool:
    """2xx 访问日志中的高频健康/推流路径。"""
    if '" 5' in text or '" 4' in text:  # 4xx/5xx 仍可见
        return False
    return any(marker in text for marker in _QUIET_ACCESS_PATH_MARKERS)


def is_websocket_connection_noise(text: str) -> bool:
    """WebSocket 正常握手由 Bot 接入状态覆盖，生产 INFO 下不逐条输出。"""
    plain = (text or "").strip()
    return plain == "connection open" or ('"WebSocket ' in plain and plain.endswith('" [accepted]'))


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
        if label == "HTTP 服务" and any(part in text for part in _TRANSIENT_UVICORN_MESSAGES):
            record.levelno = logging.WARNING
            record.levelname = "WARNING"
        elif label == "HTTP 服务" and is_websocket_connection_noise(text):
            record.levelno = logging.DEBUG
            record.levelname = "DEBUG"
        elif record.name == "uvicorn.access" and _is_quiet_access_line(text):
            record.levelno = logging.DEBUG
            record.levelname = "DEBUG"
        elif label == "HTTP 服务" and _is_transient_asgi_failure(record):
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


def install_repo_console_log_format() -> None:
    import nonebot.log as nb_log

    nb_log.logger.remove(nb_log.logger_id)
    nb_log.logger_id = nb_log.logger.add(
        sys.stdout,
        level=0,
        diagnose=False,
        filter=nb_log.default_filter,
        format=format_repo_console_log,
    )


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
        message = str(record.get("message", ""))
        plain = _COLOR_TAG_RE.sub("", message)
        if _PLUGIN_LOAD_SUCCESS_RE.search(plain) or is_matcher_lifecycle_noise(plain):
            record["level"].name = "DEBUG"
            record["level"].no = debug_no
        record["message"] = prefix_business_log_message(str(record.get("name", "")), message)

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
