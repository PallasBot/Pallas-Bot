from __future__ import annotations

from types import SimpleNamespace

from src.plugins.who_is_spy.handlers import is_group_speaking
from src.plugins.who_is_spy.logic import games, render_speech_recap, truncate_speech
from src.plugins.who_is_spy.models import Game, Player
from src.plugins.who_is_spy.speak import extract_at_speech_text


def test_extract_at_speech_text_skips_at_segments() -> None:
    event = SimpleNamespace(
        message=[
            SimpleNamespace(type="at", data={"qq": "123456"}),
            SimpleNamespace(type="text", data={"text": " 是一种水果 "}),
        ]
    )
    assert extract_at_speech_text(event) == "是一种水果"


def test_extract_at_speech_text_falls_back_to_raw_message() -> None:
    event = SimpleNamespace(
        message=[SimpleNamespace(type="text", data={"text": "两个字"})],
        raw_message="[at:qq=3599334092] 两个字",
        get_plaintext=lambda: "两个字",
    )
    assert extract_at_speech_text(event) == "两个字"


def test_is_group_speaking_uses_memory_ready_without_coord_session(monkeypatch) -> None:
    games.clear()
    game = Game(group_id=733291779, owner_id=1, ready=True)
    game.players[1] = Player(uid=1, nickname="甲")
    game.alive_order = [1]
    games[733291779] = game

    monkeypatch.setattr(
        "src.platform.multi_bot.at_targets.get_fleet_bot_ids",
        lambda: frozenset({3599334092}),
    )
    monkeypatch.setattr("src.plugins.who_is_spy.session.spy_session_active", lambda _gid: False)
    monkeypatch.setattr("src.plugins.who_is_spy.session.read_active_game_snapshot", lambda _gid: None)

    event = SimpleNamespace(
        group_id=733291779,
        message=[
            SimpleNamespace(type="at", data={"qq": "3599334092"}),
            SimpleNamespace(type="text", data={"text": " 两个字 "}),
        ],
        get_plaintext=lambda: "两个字",
    )
    assert is_group_speaking(event) is True
    games.clear()


def test_is_group_speaking_rejects_voting_phase(monkeypatch) -> None:
    games.clear()
    game = Game(group_id=1, owner_id=1, ready=True)
    game.players[1] = Player(uid=1, nickname="甲")
    game.alive_order = [1]
    game.expecting_pm_vote = {1}
    game.vote_round_tag = game.round_no
    games[1] = game

    monkeypatch.setattr(
        "src.platform.multi_bot.at_targets.get_fleet_bot_ids",
        lambda: frozenset({3599334092}),
    )

    event = SimpleNamespace(
        group_id=1,
        message=[
            SimpleNamespace(type="at", data={"qq": "3599334092"}),
            SimpleNamespace(type="text", data={"text": "描述"}),
        ],
        get_plaintext=lambda: "描述",
    )
    assert is_group_speaking(event) is False
    games.clear()


def test_truncate_speech() -> None:
    assert truncate_speech("短句", max_len=10) == "短句"
    assert truncate_speech("一二三四五六七八九十", max_len=5) == "一二三四…"


def test_render_speech_recap_by_seat() -> None:
    game = Game(group_id=1, owner_id=10, ready=True)
    game.alive_order = [10, 20, 30]
    game.players = {
        10: Player(uid=10, nickname="甲"),
        20: Player(uid=20, nickname="乙"),
        30: Player(uid=30, nickname="丙"),
    }
    game.round_speeches = {10: "红色水果", 30: "圆的"}

    text = render_speech_recap(game, max_len=40)
    assert "1. 甲：红色水果" in text
    assert "3. 丙：圆的" in text
    assert "乙" not in text
