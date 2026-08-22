"""stdlib 日志转 loguru 时补通道标签。"""

from __future__ import annotations

import logging
import re
import sys
import threading
from contextvars import ContextVar
from typing import TYPE_CHECKING

from nonebot.log import LoguruHandler

if TYPE_CHECKING:
    from logging import LogRecord
    from typing import Any

_DISPLAY_NAME_COLORS = (
    "<le>",
    "<ly>",
    "<lm>",
    "<lr>",
    "<lc>",
    "<lg>",
    "<lw>",
    "<m>",
)

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
    ("pallas.core.platform.work_jobs", "WorkAux"),
    ("packages.repeater.learn_queue", "Learn"),
    ("packages.repeater.learner", "Learn"),
    ("packages.repeater.fanout", "Reply"),
    ("packages.repeater.emoji", "Reaction"),
    ("packages.repeater", "Repeater"),
    ("packages.llm_chat.drunk_chat", "Drink"),
    ("packages.llm_chat", "Chat"),
    ("packages.pb_webui", "WebUI"),
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
    ("pallas.product.message_scrub", "Scrub"),
    ("pallas.product.community_stats", "Stats"),
    ("pallas.product", "Product"),
    ("pallas.core.platform.ai_callback", "AICallback"),
    ("pallas.core.foundation.db", "DB"),
    ("pallas.core.platform", "Platform"),
    ("pallas.core", "Core"),
    ("pallas.console.cli", "CLI"),
    ("pallas.console", "WebUI"),
    ("pallas.extensions", "Extension"),
    ("pallas", "Pallas"),
)

_DISPLAY_LOG_NAME_PREFIXES = (
    "packages.",
    "local.",
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
    if name.startswith("pallas.core.platform.work_jobs."):
        return "WorkAux"
    if name in {"pallas", "pallas.core"} or name.startswith("pallas.core."):
        return "Core"
    if name == "packages.llm_chat.drunk_chat" or name.startswith("packages.llm_chat.drunk_chat."):
        return "Drink"
    if name == "packages.llm_chat" or name.startswith("packages.llm_chat."):
        return "LLMChat"
    if name.startswith("packages."):
        return _pascal_case(name.split(".", 2)[1])
    if name.startswith("local.plugins."):
        return _pascal_case(name.split(".", 3)[2])
    for prefix in ("pallas_plugin_", "nonebot_plugin_"):
        if name.startswith(prefix):
            return _pascal_case(name.removeprefix(prefix).split(".", 1)[0])
    if name.startswith("pallas.product."):
        if name == "pallas.product.llm" or name.startswith("pallas.product.llm."):
            return "LLMChat"
        if name == "pallas.product.community_stats" or name.startswith("pallas.product.community_stats."):
            return "PbStats"
        return _pascal_case(name.split(".", 3)[2])
    if name.startswith("pallas.console."):
        return "Console"
    if name.startswith("pallas.extensions."):
        return "Extension"
    return _pascal_case(name.split(".", 1)[0]) if name else ""


_SOURCE_MODULE_EXTRA_KEY = "module_name"


def record_source_module_name(record: dict[str, Any]) -> str:
    """返回日志真实来源模块名；优先用 patcher 暂存值，绕过 NoneBot 的插件名折叠。"""
    stashed = record.get("extra", {}).get(_SOURCE_MODULE_EXTRA_KEY)
    if stashed:
        return str(stashed)
    return str(record.get("name", ""))


_PASCAL_CASE_ACRONYMS = {"llm": "LLM", "tts": "TTS"}


def _pascal_case(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parts: list[str] = []
    for part in re.split(r"[_-]+", text):
        if not part:
            continue
        lowered = part.casefold()
        parts.append(_PASCAL_CASE_ACRONYMS.get(lowered, part[:1].upper() + part[1:]))
    return "".join(parts)


def _stable_hash(text: str) -> int:
    h = 0
    for ch in text:
        h = (h * 31 + ord(ch)) & 0x7FFFFFFF
    return h


def _display_name_color(display_name: str) -> str:
    """按显示名稳定映射一个 loguru 颜色标记，同名同色。"""
    return _DISPLAY_NAME_COLORS[_stable_hash(display_name) % len(_DISPLAY_NAME_COLORS)]


def _log_prefix_label(logger_name: str, message: str) -> str:
    """返回业务前缀标签（不含方括号）；调用方消息已有 ``[`` 前缀则不重复加。"""
    text = str(message or "").lstrip()
    if not text or text.startswith("["):
        return ""
    name = (logger_name or "").strip()
    for prefix, label in _BUSINESS_LOG_LABELS:
        if name == prefix or name.startswith(f"{prefix}.") or (prefix.endswith("_") and name.startswith(prefix)):
            return label
    if name.startswith(_DISPLAY_LOG_NAME_PREFIXES):
        return display_log_name(name)
    return ""


_RAW_MESSAGE_EXTRA_KEY = "raw_message"
# 调用方可用 ``logger.bind(display_name=...)`` 覆盖通道名，同时抑制模块业务标签注入
_DISPLAY_NAME_EXTRA_KEY = "display_name"

# 消息行首业务标签：字母/中文/连字符/点/下划线，词间允许单空格；不含数字，
# 避免误拆 ``[Bot 1111]``/``[群 123]``/``[用户发送了 3 张图片]`` 等正文
_TAG_WORD = r"[A-Za-z\u4e00-\u9fff][A-Za-z\u4e00-\u9fff.\-_]*"
_LEADING_TAG_RE = re.compile(rf"^\[(?P<tag>{_TAG_WORD}(?: {_TAG_WORD})*)\]\s?(?P<body>[\s\S]*)$")


def _leading_business_tag(message: str) -> tuple[str, str]:
    """拆出消息行首业务标签（如 ``[Ready]``/``[初始化]``），返回 (tag, body)。"""
    m = _LEADING_TAG_RE.match(str(message or ""))
    if not m:
        return "", str(message or "")
    return m.group("tag"), m.group("body")


def _compose_repo_log_template(record: dict[str, Any], *, console: bool) -> str:
    """动态拼接日志模板：模块名与业务前缀按来源稳定配色。"""
    name = record_source_module_name(record)
    override = str(record["extra"].get(_DISPLAY_NAME_EXTRA_KEY) or "").strip()
    display = override or display_log_name(name)
    record["extra"][_DISPLAY_NAME_EXTRA_KEY] = display
    color = _display_name_color(display)
    raw = record["extra"].get(_RAW_MESSAGE_EXTRA_KEY)
    if raw is None:
        raw = str(record.get("message") or "")
        record["extra"][_RAW_MESSAGE_EXTRA_KEY] = raw
    tag, body = _leading_business_tag(raw)
    if tag:
        record["message"] = body
        prefix = f"{color}[{tag}]</> " if console else f"[{tag}] "
    elif not override:
        label = _log_prefix_label(name, raw)
        prefix = f"{color}[{label}]</> " if console and label else f"[{label}] " if label else ""
    else:
        prefix = ""
    if console:
        display_part = color + "{{{extra[display_name]:<8}}}</>"
        return (
            "<g>{time:MM-DD HH:mm:ss}</g> [<lvl>{level:<8}</lvl>] "
            f"{display_part} {prefix}"
            "{message}\n{exception}"
        )
    display_part = "{{{extra[display_name]:<8}}}"
    return f"{{time:MM-DD HH:mm:ss}} [{{level:<8}}] {display_part} {prefix}{{message}}\n{{exception}}"


def format_repo_console_log(record: dict[str, Any]) -> str:
    return _compose_repo_log_template(record, console=True)


def format_repo_file_log(record: dict[str, Any]) -> str:
    return _compose_repo_log_template(record, console=False)


def _dotted_pascal_case(value: str) -> str:
    """按点分段转紧凑 PascalCase，未匹配别名的 stdlib logger 名兜底展示。"""
    return _pascal_case(str(value or "").replace(".", "_"))


def _stdlib_logger_channel_label(logger_name: str) -> str:
    """把 stdlib logger 名收成简短标签；``.error`` 易被误认为级别，故单独映射。"""
    name = (logger_name or "").strip()
    if name == "uvicorn.error":
        return "HTTP 服务"
    for prefix, alias in _CHANNEL_ALIASES:
        if name == prefix.rstrip(".") or name.startswith(prefix):
            return alias
    return _dotted_pascal_case(name)


def prefix_business_log_message(logger_name: str, message: str) -> str:
    """为主仓业务日志补充稳定类别标签，保留调用方已有标签。"""
    label = _log_prefix_label(logger_name, message)
    if not label:
        return str(message)
    return f"[{label}] {str(message).lstrip()}"


def format_business_event(action: str, result: str, /, **fields: object) -> str:
    """生成单行英文结果叙事，省略空字段。"""
    if action == "复读回复" and result == "已发送":
        bot = fields.get("bot")
        group = fields.get("group")
        content = _format_business_field(fields.get("content"))
        tag = "Fanout" if fields.get("mode") == "fanout" else "Reply"
        return f"[{tag}] Bot [{bot}] replied in group [{group}]: {content}"
    if action == "饮酒" and result == "已完成":
        bot = fields.get("bot")
        group = fields.get("group")
        duration = fields.get("duration")
        return f"[Drink] Bot [{bot}] started drinking in group [{group}], sober up after {duration}s."
    if action == "清醒" and result == "已完成":
        return f"[SoberUp] Bot [{fields.get('bot')}] sobered up in group [{fields.get('group')}]."
    if action == "酒后会话" and result == "已完成":
        return (
            f"[Session] Bot [{fields.get('bot')}] cleared drunk-chat session [{fields.get('session_id')}] "
            f"in group [{fields.get('group')}]."
        )
    if action == "表情回应" and result == "已发送":
        return (
            f"[Reaction] Bot [{fields.get('bot')}] reacted to message [{fields.get('message_id')}] "
            f"in group [{fields.get('group')}] with emoji [{fields.get('emoji')}]."
        )
    if action == "表情回应" and result == "已跳过":
        return (
            f"[Reaction] Bot [{fields.get('bot')}] skipped message [{fields.get('message_id')}] "
            f"in group [{fields.get('group')}]: already reacted."
        )
    if action == "表情回应" and result == "已超时":
        return (
            f"[Reaction] Bot [{fields.get('bot')}] timed out reacting to message [{fields.get('message_id')}] "
            f"in group [{fields.get('group')}] after [{fields.get('timeout')}s]."
        )
    if action == "表情回应" and result == "发送失败":
        return (
            f"[Reaction] Bot [{fields.get('bot')}] failed to react to message [{fields.get('message_id')}] "
            f"in group [{fields.get('group')}] with emoji [{fields.get('emoji')}]: {fields.get('error')}."
        )
    if action == "自动表情回应" and result == "已跳过":
        return (
            f"[Reaction] Bot [{fields.get('bot')}] skipped auto reaction for message [{fields.get('message_id')}] "
            f"in group [{fields.get('group')}]: pending [{fields.get('pending')}] "
            f"reached limit [{fields.get('limit')}]."
        )
    if action == "发送队列" and result == "失败":
        return f"[SendQueue] Bot [{fields.get('bot')}] failed {fields.get('api')}: {fields.get('error')}"
    if action == "语料回填批次" and result == "已完成":
        return (
            f"[Corpus] backfill batch completed, pushed [{fields.get('pushed')}], "
            f"skipped [{fields.get('skipped')}], cursor [{fields.get('cursor') or '-'}]"
        )
    if action == "发送队列" and result == "可能已投递":
        return (
            f"[SendQueue] Bot [{fields.get('bot')}] send {fields.get('api')} timed out, "
            f"message may have been delivered: {fields.get('error')}"
        )

    subject = _BUSINESS_EVENT_ACTIONS.get(action, action)
    outcome = _BUSINESS_EVENT_RESULTS.get(result, result)
    text = f"{subject} {outcome}".strip()
    values = [f"{key}={_format_business_field(value)}" for key, value in fields.items() if value not in (None, "")]
    return f"{text}: {' '.join(values)}" if values else text


def format_plugin_event(
    operation: str,
    narrative: str,
    /,
) -> str:
    """生成带 PascalCase 操作标签的单行领域叙事。"""
    tag = _pascal_case(operation.strip())
    text = _format_business_field(narrative).strip()
    return f"[{tag}] {text}" if text else f"[{tag}]"


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


command_traffic_ctx: ContextVar[bool] = ContextVar("pallas_command_traffic", default=False)


def is_matcher_lifecycle_noise(plain: str, *, command_traffic: bool = False) -> bool:
    """NoneBot Matcher 生命周期 INFO：非命令态每事件数行，生产 INFO 下应降为 DEBUG。

    命令态（``command_traffic_ctx`` 由 ingress 在命令分发时置位）下放行
    ``Event will be handled by`` 一行，便于用户确认命令已进入执行。
    """
    text = (plain or "").strip()
    if not text:
        return False
    if text.startswith("Event will be handled by "):
        return not command_traffic
    if text.endswith(" running complete") or " running is cancelled" in text:
        return True
    # 「Event foo.bar is ignored」；勿匹配 Error … Event ignored!
    if text.startswith("Event ") and text.endswith(" is ignored"):
        return True
    return False


def _build_noise_patcher(logger, _log_patcher):
    debug_no = logger.level("DEBUG").no

    def patcher(record: dict[str, Any]) -> None:
        record["extra"][_SOURCE_MODULE_EXTRA_KEY] = str(record.get("name", ""))
        _log_patcher(record)
        message = str(record.get("message", ""))
        plain = _COLOR_TAG_RE.sub("", message)
        if _PLUGIN_LOAD_SUCCESS_RE.search(plain) or is_matcher_lifecycle_noise(
            plain, command_traffic=command_traffic_ctx.get()
        ):
            record["level"].name = "DEBUG"
            record["level"].no = debug_no

    return patcher


def install_startup_log_noise_patcher() -> None:
    """在 ``nonebot.init()`` 之后调用：压制启动与 Matcher 生命周期刷屏。

    - 插件逐条 Succeeded → DEBUG（摘要已有 ``[启动] 就绪``）
    - Matcher handled / complete / cancelled / ignored → DEBUG
    """
    from nonebot import _log_patcher
    from nonebot.log import logger

    _install_log_noise_patcher(logger, _log_patcher)


def _install_log_noise_patcher(logger, _log_patcher) -> None:
    """按当前日志级别（重）安装 noise patcher；TRACE/DEBUG 下不安装。"""
    level_name = resolve_repo_log_level()
    if level_name in {"TRACE", "DEBUG"}:
        return
    logger.configure(patcher=_build_noise_patcher(logger, _log_patcher))


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


_FILE_SINK_ID: int | None = None
_FILE_SINK_ARGS: dict[str, Any] | None = None
_FILE_SINK_LOG_PATH_DEFAULT = "nonebot_runtime.log"
_FILE_SINK_LOCK = threading.RLock()


def register_repo_file_sink(
    logger,
    fmt,
    *,
    path=None,
    rotation="50 MB",
    retention="14 days",
    encoding="utf-8",
    enqueue=True,
) -> int:
    """登记主文件 sink id 与重建参数，供运行时调整日志级别。

    boot.py 用它替代裸 ``logger.add``；WebUI 改级别时 remove + 原位重建。
    """
    global _FILE_SINK_ID, _FILE_SINK_ARGS
    with _FILE_SINK_LOCK:
        if _FILE_SINK_ID is not None:
            try:
                logger.remove(_FILE_SINK_ID)
            except Exception:
                pass
        _FILE_SINK_ARGS = {
            "path": path or _FILE_SINK_LOG_PATH_DEFAULT,
            "rotation": rotation,
            "retention": retention,
            "encoding": encoding,
            "enqueue": enqueue,
        }
        _FILE_SINK_ID = logger.add(
            _FILE_SINK_ARGS["path"],
            level=resolve_repo_log_level(),
            format=fmt,
            rotation=_FILE_SINK_ARGS["rotation"],
            retention=_FILE_SINK_ARGS["retention"],
            encoding=_FILE_SINK_ARGS["encoding"],
            enqueue=_FILE_SINK_ARGS["enqueue"],
        )
        return _FILE_SINK_ID


def reapply_runtime_log_level() -> None:
    """保存 WebUI 日志级别后，把 patcher、NoneBot 默认过滤与文件 sink 级别同步。"""
    global _FILE_SINK_ID
    from nonebot import _log_patcher
    from nonebot.log import logger

    _install_log_noise_patcher(logger, _log_patcher)
    level = resolve_repo_log_level()
    try:
        logger.configure(extra={"nonebot_log_level": level})
    except Exception:
        pass
    with _FILE_SINK_LOCK:
        if _FILE_SINK_ID is not None:
            try:
                logger.remove(_FILE_SINK_ID)
            except Exception:
                pass
            _FILE_SINK_ID = None
        if _FILE_SINK_ARGS is not None:
            register_repo_file_sink(
                logger,
                format_repo_file_log,
                path=_FILE_SINK_ARGS["path"],
                rotation=_FILE_SINK_ARGS["rotation"],
                retention=_FILE_SINK_ARGS["retention"],
                encoding=_FILE_SINK_ARGS["encoding"],
                enqueue=_FILE_SINK_ARGS["enqueue"],
            )
