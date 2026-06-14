from __future__ import annotations

from src.plugins.who_is_spy.args import parse_undercover_count


def test_parse_undercover_count_from_text() -> None:
    assert parse_undercover_count("2", default=1) == 2
    assert parse_undercover_count("", default=1) == 1


def test_parse_undercover_count_clamped() -> None:
    assert parse_undercover_count("9", default=1) == 3
    assert parse_undercover_count("0", default=2) == 1
