import ast
import logging
from pathlib import Path

from pallas.api.logging import format_plugin_event
from pallas.core.foundation.logging import event_log
from pallas.core.foundation.logging.bridge import (
    REPO_CONSOLE_LOG_FORMAT,
    REPO_FILE_LOG_FORMAT,
    ChannelLoguruHandler,
    _stdlib_logger_channel_label,
    display_log_name,
    format_business_event,
    format_repo_console_log,
    format_repo_file_log,
    is_matcher_lifecycle_noise,
    is_websocket_connection_noise,
    prefix_business_log_message,
    record_source_module_name,
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
    assert "{{{extra[display_name]:<8}}}" in REPO_CONSOLE_LOG_FORMAT
    assert "{level:<8}" in REPO_FILE_LOG_FORMAT
    assert "{{{extra[display_name]:<8}}}" in REPO_FILE_LOG_FORMAT


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
    assert display_log_name("packages.llm_chat.chat_message") == "LLMChat"
    assert display_log_name("packages.llm_chat.drunk_chat") == "Drink"
    assert display_log_name("pallas_plugin_protocol.runtime") == "Protocol"
    assert display_log_name("nonebot_plugin_apscheduler") == "Apscheduler"


def test_repo_file_log_formatter_ends_each_record_with_a_newline() -> None:
    record = {"name": "pallas", "extra": {}}

    assert format_repo_file_log(record).endswith("\n")


def test_record_source_module_name_prefers_patcher_stash() -> None:
    stashed = {"name": "pallas", "extra": {"module_name": "pallas.core.platform.ai_callback.runner"}}
    assert record_source_module_name(stashed) == "pallas.core.platform.ai_callback.runner"
    assert record_source_module_name({"name": "pallas", "extra": {}}) == "pallas"


def test_format_uses_stashed_module_for_display_name() -> None:
    record = {"name": "pallas", "extra": {"module_name": "pallas.product.llm.delivery"}}

    format_repo_console_log(record)

    assert record["extra"]["display_name"] == "LLMChat"


def test_display_log_name_maps_product_llm_to_llm_chat() -> None:
    assert display_log_name("pallas.product.llm.delivery") == "LLMChat"
    assert display_log_name("pallas.product.persona.expression_learn") == "Persona"


def test_business_log_messages_get_module_labels_without_duplicates() -> None:
    assert prefix_business_log_message("packages.repeater.learn_queue", "queued batch") == "[Learn] queued batch"
    assert prefix_business_log_message("packages.repeater.fanout_reply", "[Reply] sent") == "[Reply] sent"
    assert prefix_business_log_message("packages.llm_chat.chat_message", "completed") == "[Chat] completed"
    assert (
        prefix_business_log_message("pallas.core.platform.ai_callback.runner", "AI callback resolved task=x")
        == "[AICallback] AI callback resolved task=x"
    )
    assert prefix_business_log_message("packages.llm_chat.drunk_chat", "session cleared") == "[Drink] session cleared"
    assert prefix_business_log_message("packages.roulette.service", "started") == "[Roulette] started"
    assert prefix_business_log_message("pallas_plugin_protocol.runtime", "started") == "[Protocol] started"
    assert prefix_business_log_message("nonebot_plugin_apscheduler", "job added") == "[Apscheduler] job added"
    assert prefix_business_log_message("pallas.product.llm.client", "request failed") == "[LLM] request failed"
    assert prefix_business_log_message("packages.pb_webui.api", "started") == "[WebUI] started"
    assert prefix_business_log_message("pallas.console.webui.console_login", "auth ok") == "[WebUI] auth ok"
    assert prefix_business_log_message("pallas.core.foundation.db.repository_pg", "connected") == "[DB] connected"
    assert prefix_business_log_message("pallas.product.message_scrub.filter", "skipped") == "[Scrub] skipped"
    assert prefix_business_log_message("third_party.client", "unchanged") == "unchanged"


def test_format_business_event_writes_action_tagged_narratives() -> None:
    assert format_business_event("复读回复", "已发送", bot=10001, group=20002, content="line one\nline two") == (
        "[Reply] Bot [10001] replied in group [20002]: line one\\nline two"
    )
    assert format_business_event("复读回复", "已发送", bot=10001, group=20002, mode="fanout", content="ok") == (
        "[Fanout] Bot [10001] replied in group [20002]: ok"
    )
    assert format_business_event("饮酒", "已完成", bot=10001, group=20002, duration=133) == (
        "[Drink] Bot [10001] started drinking in group [20002], sober up after 133s."
    )
    assert (
        format_business_event("清醒", "已完成", bot=10001, group=20002)
        == "[SoberUp] Bot [10001] sobered up in group [20002]."
    )
    assert format_business_event("酒后会话", "已完成", bot=10001, group=20002, session_id="10001_20002") == (
        "[Session] Bot [10001] cleared drunk-chat session [10001_20002] in group [20002]."
    )
    assert format_business_event("表情回应", "已发送", bot=10001, group=20002, message_id=99, emoji="66") == (
        "[Reaction] Bot [10001] reacted to message [99] in group [20002] with emoji [66]."
    )
    assert format_business_event("表情回应", "已跳过", bot=10001, group=20002, message_id=99) == (
        "[Reaction] Bot [10001] skipped message [99] in group [20002]: already reacted."
    )
    assert format_business_event("表情回应", "已超时", bot=10001, group=20002, message_id=99, timeout=5) == (
        "[Reaction] Bot [10001] timed out reacting to message [99] in group [20002] after [5s]."
    )
    assert (
        format_business_event(
            "表情回应", "发送失败", bot=10001, group=20002, message_id=99, emoji="66", error="ActionFailed"
        )
        == "[Reaction] Bot [10001] failed to react to message [99] in group [20002] with emoji [66]: ActionFailed."
    )
    assert format_business_event(
        "自动表情回应", "已跳过", bot=10001, group=20002, message_id=99, pending=64, limit=64
    ) == (
        "[Reaction] Bot [10001] skipped auto reaction for message [99] in group [20002]: "
        "pending [64] reached limit [64]."
    )
    assert format_business_event("语料回填批次", "已跳过", reason=None) == "Corpus backfill batch skipped"


def test_format_plugin_event_writes_pascal_case_operation_narrative() -> None:
    assert format_plugin_event("ready", "Registered command [Draw]") == "[Ready] Registered command [Draw]"
    assert (
        format_plugin_event(
            "draw",
            "Bot [100000001] drew [The Fool upright] for user [100000003] in group [100000002] in [18ms]",
        )
        == "[Draw] Bot [100000001] drew [The Fool upright] for user [100000003] in group [100000002] in [18ms]"
    )
    assert (
        format_plugin_event(
            "clear_session",
            "Bot [100000001] cleared session [100000001_100000002] in group [100000002]",
        )
        == "[ClearSession] Bot [100000001] cleared session [100000001_100000002] in group [100000002]"
    )


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
