import logging

from pallas.core.foundation.logging import event_log
from pallas.core.foundation.logging.bridge import (
    REPO_CONSOLE_LOG_FORMAT,
    ChannelLoguruHandler,
    _stdlib_logger_channel_label,
    is_matcher_lifecycle_noise,
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
    assert "{{{name:<12}}}" in REPO_CONSOLE_LOG_FORMAT


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
