from __future__ import annotations

from src.plugins.who_is_spy.copy import game_over_tail, room_closed, word_pair_line


def test_word_pair_line() -> None:
    assert word_pair_line(civilian_word="可乐", undercover_word="雪碧") == "本局词对：平民「可乐」｜卧底「雪碧」"
    assert word_pair_line(civilian_word="", undercover_word="雪碧") == ""


def test_game_over_tail_includes_word_pair() -> None:
    text = game_over_tail(civilian_word="饺子", undercover_word="馄饨")
    assert "本局结束" in text
    assert "平民「饺子」" in text
    assert "卧底「馄饨」" in text


def test_room_closed_includes_word_pair_when_started() -> None:
    text = room_closed(civilian_word="拿铁", undercover_word="美式")
    assert text.startswith("房间已关。")
    assert "平民「拿铁」" in text


def test_room_closed_prep_room_has_no_word_pair() -> None:
    assert room_closed() == "房间已关。"
