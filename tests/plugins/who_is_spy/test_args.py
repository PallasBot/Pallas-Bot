from __future__ import annotations

from src.plugins.who_is_spy.args import parse_start_args, parse_undercover_count


def test_parse_undercover_count_from_text() -> None:
    assert parse_undercover_count("2", default=1) == 2
    assert parse_undercover_count("", default=1) == 1


def test_parse_undercover_count_clamped() -> None:
    assert parse_undercover_count("9", default=1) == 3
    assert parse_undercover_count("0", default=2) == 1


def test_parse_start_args_hide_role() -> None:
    undercover, blank, show_role = parse_start_args(
        "2 暗牌",
        default_undercovers=1,
        default_blanks=0,
        default_show_role=True,
    )
    assert undercover == 2
    assert blank == 0
    assert show_role is False


def test_parse_start_args_show_role() -> None:
    undercover, blank, show_role = parse_start_args(
        "明牌",
        default_undercovers=1,
        default_blanks=0,
        default_show_role=False,
    )
    assert undercover == 1
    assert blank == 0
    assert show_role is True


def test_parse_start_args_blank_token() -> None:
    undercover, blank, show_role = parse_start_args(
        "1 白板2",
        default_undercovers=1,
        default_blanks=0,
        default_show_role=False,
    )
    assert undercover == 1
    assert blank == 2
    assert show_role is False


def test_parse_start_args_no_blank() -> None:
    _, blank, _ = parse_start_args(
        "无白板",
        default_undercovers=1,
        default_blanks=1,
        default_show_role=False,
    )
    assert blank == 0
