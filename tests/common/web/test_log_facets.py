import pytest

from src.common.web.bot_web import nonebot_log_record_matches_http_facet


@pytest.mark.parametrize(
    ("name", "message", "expected_webui", "expected_protocol"),
    [
        ("pallas_webui", "hello", True, False),
        ("other", "[pallas-webui] x", True, False),
        ("pallas_protocol", "y", False, True),
        ("x", "[pallas-protocol] z", False, True),
        ("nonebot", "plain", False, False),
    ],
)
def test_http_facet_matching(
    name: str,
    message: str,
    expected_webui: bool,
    expected_protocol: bool,
) -> None:
    rec = {"name": name, "message": message}
    assert nonebot_log_record_matches_http_facet(rec, "webui") is expected_webui
    assert nonebot_log_record_matches_http_facet(rec, "protocol") is expected_protocol
