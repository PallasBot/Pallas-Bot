from packages.help.help_args import parse_help_page_token


def test_parse_help_page_token_variants() -> None:
    assert parse_help_page_token("2页") == 2
    assert parse_help_page_token("第3页") == 3
    assert parse_help_page_token("p4") == 4
    assert parse_help_page_token("P5") == 5
    assert parse_help_page_token("页6") == 6


def test_parse_help_page_token_rejects_plugin_like() -> None:
    assert parse_help_page_token("MAA远控") is None
    assert parse_help_page_token("12") is None
