import pytest

from pallas.console.web.bot_web import (
    classify_log_facet,
    entry_matches_log_scope,
    resolve_entry_facet,
)


@pytest.mark.parametrize(
    ("name", "message", "expected"),
    [
        ("pb_webui", "hello", "console"),
        ("pallas_webui", "hello", "console"),
        ("other", "[pallas-webui] x", "console"),
        (
            "uvicorn.access",
            '127.0.0.1:1 - "GET /pallas/api/health HTTP/1.1" 200',
            "console",
        ),
        (
            "pallas",
            '[服务] 127.0.0.1:1 - "GET /pallas/ HTTP/1.1" 200',
            "console",
        ),
        (
            "pallas",
            '[服务] 127.0.0.1:1 - "GET /health HTTP/1.1" 200',
            "other",
        ),
        (
            "repeater",
            "bot [1] ready to send [hi] to group [2] (reply)",
            "message",
        ),
        (
            "pallas",
            "OneBot V11 1 | [message.group.normal]: Message 1 from 2@[群:3] 'hi'",
            "message",
        ),
        (
            "pallas",
            "Bot [1] 群 [2] 用户 [3]: hi",
            "message",
        ),
        (
            "pallas",
            "[Bot 1] [群 2] [用户 3] hi",
            "message",
        ),
        (
            "nonebot",
            "Event will be handled by Matcher(type='message', module=packages.repeater.handlers.message, lineno=41)",
            "message",
        ),
        ("nonebot", "OneBot V11 | Calling API send_msg", "message"),
        ("nonebot", "OneBot V11 | Calling API get_status", "other"),
        ("nonebot", "plain", "other"),
        ("pb_protocol", "y", "other"),
    ],
)
def test_classify_log_facet(name: str, message: str, expected: str) -> None:
    rec = {"name": name, "message": message}
    entry = {"scope": name, "message": message}
    assert classify_log_facet(rec, entry) == expected
    assert classify_log_facet(None, entry) == expected


@pytest.mark.parametrize(
    ("rec", "expected"),
    [
        ({}, "other"),
        ({"name": None}, "other"),
        ({"message": None}, "other"),
        ({"name": "", "message": ""}, "other"),
        ({"name": "nonebot", "message": None}, "other"),
        ({"name": "nonebot", "message": 123}, "other"),
        ({"message": "[pallas-webui] z"}, "console"),
        ({"name": "pallas_webui"}, "console"),
        ({"name": "pb_webui"}, "console"),
    ],
)
def test_classify_log_facet_edge_records(rec: dict, expected: str) -> None:
    assert classify_log_facet(rec, None) == expected


def test_missing_facet_treated_as_other() -> None:
    entry = {"id": 1, "scope": "nonebot", "message": "plain"}
    assert resolve_entry_facet(entry) == "other"
    assert entry_matches_log_scope(entry, "all") is True
    assert entry_matches_log_scope(entry, "other") is True
    assert entry_matches_log_scope(entry, "message") is False
    assert entry_matches_log_scope(entry, "console") is False


def test_entry_matches_log_scope_by_facet() -> None:
    assert entry_matches_log_scope({"facet": "message"}, "message") is True
    assert entry_matches_log_scope({"facet": "console"}, "console") is True
    assert entry_matches_log_scope({"facet": "other"}, "other") is True
    assert entry_matches_log_scope({"facet": "message"}, "console") is False
    assert entry_matches_log_scope({"facet": "console"}, "all") is True


def test_console_priority_over_message_markers() -> None:
    """控制台 access 优先于消息面关键字。"""
    rec = {
        "name": "pb_webui",
        "message": "ready to send should not win",
    }
    assert classify_log_facet(rec, None) == "console"


def test_line_matches_scope_missing_is_other() -> None:
    from pallas.core.platform.shard.logs.view import _line_matches_scope

    plain = "07-28 10:53:00 | INFO     | nonebot:1 - plain"
    assert _line_matches_scope(plain, "all") is True
    assert _line_matches_scope(plain, "other") is True
    assert _line_matches_scope(plain, "message") is False
    assert _line_matches_scope(plain, "console") is False

    msg = "07-28 10:59:20 | INFO     | repeater:1 - bot [1] ready to send [hi] to group [2] (reply)"
    assert _line_matches_scope(msg, "message") is True
    assert _line_matches_scope(msg, "other") is False
    assert _line_matches_scope(plain, "protocol") is True


def test_protocol_log_facet_compatibility_is_removed() -> None:
    import pallas.console.web as web

    assert not hasattr(web, "nonebot_log_record_matches_http_facet")
