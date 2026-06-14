from __future__ import annotations

from src.plugins.who_is_spy.coord_store import game_from_snapshot, game_to_snapshot, prep_players_from_game
from src.plugins.who_is_spy.models import Game, Player


def test_game_snapshot_roundtrip() -> None:
    game = Game(group_id=733291779, owner_id=1, ready=True)
    game.word_civilian = "苹果"
    game.word_undercover = "梨"
    game.round_no = 2
    game.vote_round_tag = 2
    game.alive_order = [10, 20, 30]
    game.expecting_pm_vote = {10, 20}
    game.votes = {10: 20, 20: None}
    game.vote_box = {20: 1}
    game.round_speeches = {10: "红色", 30: "甜的"}
    game.players = {
        10: Player(uid=10, nickname="甲", has_spoken_this_round=True),
        20: Player(uid=20, nickname="乙", is_undercover=True),
        30: Player(uid=30, nickname="丙", is_blank=True),
    }

    restored = game_from_snapshot(game_to_snapshot(game))
    assert restored is not None
    assert restored.group_id == game.group_id
    assert restored.ready is True
    assert restored.word_civilian == "苹果"
    assert restored.alive_order == [10, 20, 30]
    assert restored.players[20].is_undercover is True
    assert restored.players[30].is_blank is True
    assert restored.round_speeches == {10: "红色", 30: "甜的"}
    assert restored.votes[20] is None
    assert restored.expecting_pm_vote == {10, 20}


def test_prep_players_from_game() -> None:
    game = Game(group_id=1, owner_id=10)
    game.players[10] = Player(uid=10, nickname="房主")
    game.players[20] = Player(uid=20, nickname="路人")
    rows = prep_players_from_game(game)
    assert rows == [{"uid": 10, "nickname": "房主"}, {"uid": 20, "nickname": "路人"}]
