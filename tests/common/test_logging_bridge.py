import ast
import io
import logging
import re
from pathlib import Path

from pallas.api.logging import format_plugin_event
from pallas.core.foundation.logging import event_log
from pallas.core.foundation.logging.bridge import (
    ChannelLoguruHandler,
    _display_name_color,
    _log_prefix_label,
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


def test_repo_console_log_template_colors_display_and_prefix() -> None:
    record = {"name": "pallas.core.platform.work_jobs.worker", "extra": {}, "message": "work aux: started"}

    template = format_repo_console_log(record)

    assert "{time:MM-DD HH:mm:ss}" in template
    assert "{level:<8}" in template
    assert "{message}\n{exception}" in template
    assert "extra[display_name]:<8" in template
    assert "[WorkAux]" in template
    assert "<g>" in template
    assert "<lvl>" in template
    assert record["name"] == "pallas.core.platform.work_jobs.worker"
    assert record["extra"]["display_name"] == "WorkAux"


def test_repo_file_log_template_keeps_plain_text_with_prefix() -> None:
    record = {"name": "pallas.core.platform.work_jobs.worker", "extra": {}, "message": "work aux: started"}

    template = format_repo_file_log(record)

    assert "{time:MM-DD HH:mm:ss}" in template
    assert "{message}\n{exception}" in template
    assert "extra[display_name]:<8" in template
    assert "[WorkAux]" in template
    assert re.search(r"<[a-z]+>", template) is None


def test_repo_console_log_template_colors_leading_message_tag() -> None:
    record = {"name": "packages.pb_webui.extended_api", "extra": {}, "message": "[Ready] pb_webui 就绪"}

    template = format_repo_console_log(record)

    assert "[Ready]" in template
    assert re.search(r"<[a-z]+>\[Ready\]</>", template) is not None
    assert record["message"] == "pb_webui 就绪"
    assert record["extra"]["raw_message"] == "[Ready] pb_webui 就绪"


def test_repo_console_log_template_keeps_bot_bracket_untouched() -> None:
    record = {"name": "packages.repeater.fanout", "extra": {}, "message": "[Bot 1001] [群 20002] 普通消息正文"}

    template = format_repo_console_log(record)

    assert "[Bot 1001]" not in template
    assert "{message}\n{exception}" in template
    assert record["message"] == "[Bot 1001] [群 20002] 普通消息正文"


def test_display_name_color_is_stable_and_bound() -> None:
    assert _display_name_color("WorkAux") == _display_name_color("WorkAux")
    assert _display_name_color("Core") == _display_name_color("Core")
    assert _display_name_color("WorkAux") in {
        "<le>",
        "<ly>",
        "<lm>",
        "<lr>",
        "<lc>",
        "<lg>",
        "<lw>",
        "<m>",
    }


def test_log_prefix_label_skips_when_message_already_tagged() -> None:
    assert _log_prefix_label("pallas.core.platform.work_jobs.worker", "work aux: started") == "WorkAux"
    assert _log_prefix_label("pallas.core.foundation.db.repository_pg", "connected") == "DB"
    assert _log_prefix_label("pallas.core.platform.work_jobs.worker", "[Reply] already tagged") == ""
    assert _log_prefix_label("third_party.client", "unchanged") == ""


def test_repo_file_log_format_renders_exception_traceback() -> None:
    from loguru import logger

    buf = io.StringIO()
    handler_id = logger.add(buf, level=0, colorize=False, format=format_repo_file_log)
    try:
        try:
            raise ValueError("secret root cause")
        except ValueError:
            logger.opt(exception=True).error("boom")
    finally:
        logger.remove(handler_id)

    out = buf.getvalue()
    assert "boom" in out
    assert "secret root cause" in out
    assert "ValueError" in out
    assert "test_repo_file_log_format_renders_exception_traceback" in out


def test_repo_console_log_renders_colors_in_terminal_and_plain_elsewhere() -> None:
    from loguru import logger

    def emit():
        patched = logger.patch(lambda record: record.update(name="pallas.core.platform.work_jobs.worker"))
        patched.warning("work aux: some event happened")
        patched.info("[Ready] pb_webui 就绪")
        patched.info("[初始化] 插件载入中")
        patched.info("[Bot 1001] [群 20002] 普通消息正文")

    colored = io.StringIO()
    handler_id = logger.add(colored, level=0, colorize=True, format=format_repo_console_log)
    try:
        emit()
    finally:
        logger.remove(handler_id)
    out = colored.getvalue()
    assert "\x1b[" in out
    assert "[WorkAux]" in out
    assert "<le>" not in out
    assert "<c>" not in out

    plain = io.StringIO()
    handler_id = logger.add(plain, level=0, colorize=False, format=format_repo_console_log)
    try:
        emit()
    finally:
        logger.remove(handler_id)
    out = plain.getvalue()
    assert "\x1b[" not in out
    assert "[WorkAux]" in out
    assert "<le>" not in out
    assert "<c>" not in out


def test_repo_console_log_uses_core_display_name_without_rewriting_logger_name() -> None:
    record = {"name": "pallas.core", "extra": {}}

    template = format_repo_console_log(record)

    assert "extra[display_name]:<8" in template
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
    assert display_log_name("pallas.core.platform.work_jobs.worker") == "WorkAux"
    assert display_log_name("pallas.core.platform.work_jobs.result_committer") == "WorkAux"


def test_repo_file_log_formatter_ends_each_record_with_a_newline() -> None:
    record = {"name": "pallas", "extra": {}}

    assert format_repo_file_log(record).endswith("\n{exception}")
    assert "{message}\n{exception}" in format_repo_file_log(record)


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
    assert (
        prefix_business_log_message(
            "pallas.core.platform.work_jobs.worker",
            "work aux: claimed [3] jobs of kinds [repeater.learn] by owner [host:1:0]",
        )
        == "[WorkAux] work aux: claimed [3] jobs of kinds [repeater.learn] by owner [host:1:0]"
    )
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
    assert (
        format_business_event(
            "发送队列", "失败", bot=10001, api="set_msg_emoji_like", error="ActionFailed(already set)"
        )
        == "[SendQueue] Bot [10001] failed set_msg_emoji_like: ActionFailed(already set)"
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
