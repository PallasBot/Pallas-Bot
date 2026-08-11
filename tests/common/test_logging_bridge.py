import ast
import logging
from pathlib import Path

from pallas.core.foundation.logging import event_log
from pallas.core.foundation.logging.bridge import (
    REPO_CONSOLE_LOG_FORMAT,
    ChannelLoguruHandler,
    _stdlib_logger_channel_label,
    display_log_name,
    format_business_event,
    format_repo_console_log,
    format_repo_file_log,
    is_matcher_lifecycle_noise,
    is_websocket_connection_noise,
    prefix_business_log_message,
)
from pallas.core.foundation.logging.event_log import (
    compact_inbound_event_log,
    inbound_event_log_as_debug,
)


def test_channel_handler_downgrades_transient_uvicorn_errors() -> None:
    handler = ChannelLoguruHandler()
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="keepalive ping failed",
        args=(),
        exc_info=None,
    )
    handler.emit(record)
    assert record.levelno == logging.WARNING
    assert record.levelname == "WARNING"


def test_stdlib_logger_channel_label_uses_repo_aliases() -> None:
    assert _stdlib_logger_channel_label("pallas.product.llm.client") == "功能"
    assert _stdlib_logger_channel_label("packages.repeater.learner") == "复读"
    assert _stdlib_logger_channel_label("uvicorn.error") == "HTTP 服务"


def test_repo_console_log_format_aligns_level_and_source() -> None:
    assert "{level:<8}" in REPO_CONSOLE_LOG_FORMAT
    assert "{{{extra[display_name]:<12}}}" in REPO_CONSOLE_LOG_FORMAT


def test_repo_console_log_uses_core_display_name_without_rewriting_logger_name() -> None:
    record = {"name": "pallas.core", "extra": {}}

    assert format_repo_console_log(record) == REPO_CONSOLE_LOG_FORMAT
    assert record["name"] == "pallas.core"
    assert record["extra"]["display_name"] == "Core"


def test_repo_console_log_capitalizes_other_display_names() -> None:
    record = {"name": "repeater", "extra": {}}

    format_repo_console_log(record)

    assert record["extra"]["display_name"] == "Repeater"


def test_display_log_name_normalizes_builtin_and_external_plugin_packages() -> None:
    assert display_log_name("packages.take_name.handlers") == "TakeName"
    assert display_log_name("pallas_plugin_protocol.runtime") == "Protocol"
    assert display_log_name("nonebot_plugin_apscheduler") == "Apscheduler"


def test_repo_file_log_formatter_ends_each_record_with_a_newline() -> None:
    record = {"name": "pallas", "extra": {}}

    assert format_repo_file_log(record).endswith("\n")


def test_business_log_messages_get_module_labels_without_duplicates() -> None:
    assert prefix_business_log_message("packages.repeater.learn_queue", "queued batch") == "[Learn] queued batch"
    assert prefix_business_log_message("packages.repeater.fanout_reply", "[Reply] sent") == "[Reply] sent"
    assert prefix_business_log_message("packages.llm_chat.chat_message", "completed") == "[Chat] completed"
    assert prefix_business_log_message("packages.roulette.service", "started") == "[Roulette] started"
    assert prefix_business_log_message("pallas_plugin_protocol.runtime", "started") == "[Protocol] started"
    assert prefix_business_log_message("nonebot_plugin_apscheduler", "job added") == "[Apscheduler] job added"
    assert prefix_business_log_message("pallas.product.llm.client", "request failed") == "[LLM] request failed"
    assert prefix_business_log_message("third_party.client", "unchanged") == "unchanged"


def test_format_business_event_writes_reply_as_a_narrative_with_body() -> None:
    assert format_business_event("复读回复", "已发送", bot=10001, group=20002, content="line one\nline two") == (
        "Bot 10001 replied in group 20002: line one\\nline two"
    )
    assert format_business_event("语料回填批次", "已跳过", reason=None) == "Corpus backfill batch skipped"


def test_console_log_messages_use_bracketed_prefix() -> None:
    root = Path(__file__).parents[2]
    source_roots = (root / "packages" / "pb_webui", root / "pallas" / "console" / "webui")
    legacy_prefixes = ("Pallas-Bot 控制台:", "Pallas-Bot 控制台：", "控制台:", "控制台：")

    offenders: list[str] = []
    for source_root in source_roots:
        for path in source_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or not node.args:
                    continue
                message = node.args[0]
                if not isinstance(message, ast.Constant) or not isinstance(message.value, str):
                    continue
                if any(prefix in message.value for prefix in legacy_prefixes):
                    offenders.append(f"{path.relative_to(root)}:{node.lineno}")
                if "[控制台]  " in message.value:
                    offenders.append(f"{path.relative_to(root)}:{node.lineno}")

    assert not offenders


def test_is_matcher_lifecycle_noise() -> None:
    assert is_matcher_lifecycle_noise(
        "Event will be handled by Matcher(type='message', module=packages.repeater.handlers.message, lineno=45)"
    )
    assert is_matcher_lifecycle_noise(
        "Matcher(type='message', module=packages.llm_chat.chat_message, lineno=114) running complete"
    )
    assert is_matcher_lifecycle_noise(
        "Matcher(type='message', module=packages.repeater.handlers.message, lineno=45) running is cancelled"
    )
    assert is_matcher_lifecycle_noise("Event notice.group_msg_emoji_like.add is ignored")
    assert not is_matcher_lifecycle_noise("Error when running EventPreProcessors. Event ignored!")
    assert not is_matcher_lifecycle_noise("ingress_dispatch: stats group_messages=1")


def test_websocket_connection_handshake_noise_is_quiet_but_lifecycle_stays_visible() -> None:
    assert is_websocket_connection_noise('172.17.0.8:32864 - "WebSocket /onebot/v11/ws" [accepted]')
    assert is_websocket_connection_noise("connection open")
    assert not is_websocket_connection_noise("Application startup complete.")
    assert not is_websocket_connection_noise("connection closed")

    handler = ChannelLoguruHandler()
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="connection open",
        args=(),
        exc_info=None,
    )
    handler.emit(record)
    assert record.levelno == logging.DEBUG
    assert record.levelname == "DEBUG"


def test_compact_inbound_event_log_folds_long_url() -> None:
    long_url = "https://multimedia.nt.qq.com.cn/download?" + ("x" * 200)
    text = f"[message.group.normal]: Message 1 from 2@[群:3] '[image:file=a.gif,url={long_url}]'"
    out = compact_inbound_event_log(text, max_len=240)
    assert "…" in out
    assert len(out) <= 240
    assert "multimedia.nt.qq.com.cn" in out


def test_compact_group_message_log_uses_readable_fields() -> None:
    out = event_log.compact_group_message_log(
        bot_id="3879348674",
        group_id=1103771828,
        user_id=2879693316,
        message="就是屁股根那里",
    )
    assert out == "[Bot 3879348674] [群 1103771828] [用户 2879693316] 就是屁股根那里"


def test_compact_group_message_log_aligns_id_fields_to_ten_digits() -> None:
    out = event_log.compact_group_message_log(
        bot_id="1",
        group_id=22,
        user_id=333,
        message="正文",
    )

    assert out == "[Bot          1] [群         22] [用户        333] 正文"


def test_inbound_log_with_angle_brackets_survives_loguru_colorizer() -> None:
    """群消息含 <le> 等时，escape 后 colors=True 不应再抛 ValueError。"""
    from loguru._colorizer import Colorizer
    from nonebot.message import escape_tag

    raw = "[message.group.normal]: Message 1 from 2@[群:3] 'foo <le> bar'"
    escaped = escape_tag(compact_inbound_event_log(raw))
    Colorizer.prepare_simple_message(escaped)


def test_inbound_event_log_as_debug_for_notice() -> None:
    assert inbound_event_log_as_debug("notice") is True
    assert inbound_event_log_as_debug("request") is True
    assert inbound_event_log_as_debug("message") is False
