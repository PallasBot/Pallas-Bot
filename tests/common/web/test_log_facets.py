import pytest

from pallas.console.web.bot_web import nonebot_log_record_matches_http_facet


@pytest.mark.parametrize(
    ("name", "message", "expected_webui", "expected_protocol"),
    [
        ("pallas_webui", "hello", True, False),
        ("other", "[pallas-webui] x", True, False),
        ("pb_protocol", "y", False, True),
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


@pytest.mark.parametrize(
    ("rec", "expected_webui", "expected_protocol"),
    [
        ({}, False, False),
        ({"name": None}, False, False),
        ({"message": None}, False, False),
        ({"name": "", "message": ""}, False, False),
        ({"name": "nonebot", "message": None}, False, False),
        ({"name": "nonebot", "message": 123}, False, False),
        ({"message": "[pallas-webui] z"}, True, False),
        ({"name": "pallas_webui"}, True, False),
    ],
)
def test_http_facet_matching_edge_records(
    rec: dict,
    expected_webui: bool,
    expected_protocol: bool,
) -> None:
    assert nonebot_log_record_matches_http_facet(rec, "webui") is expected_webui
    assert nonebot_log_record_matches_http_facet(rec, "protocol") is expected_protocol
