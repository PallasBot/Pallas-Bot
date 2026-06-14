from __future__ import annotations

from src.plugins.who_is_spy.models import Game, Player


def test_all_alive_have_spoken() -> None:
    game = Game(group_id=1, owner_id=1, ready=True)
    game.players = {
        1: Player(uid=1, nickname="a", has_spoken_this_round=True),
        2: Player(uid=2, nickname="b"),
    }
    game.alive_order = [1, 2]
    assert game.all_alive_have_spoken() is False
    game.players[2].has_spoken_this_round = True
    assert game.all_alive_have_spoken() is True


def test_reset_round_clears_speeches() -> None:
    game = Game(group_id=1, owner_id=1, ready=True)
    game.round_no = 1
    game.round_speeches[1] = "hello"
    game.players[1] = Player(uid=1, nickname="a", has_spoken_this_round=True)
    game.reset_round_flags()
    assert game.round_no == 2
    assert game.round_speeches == {}
    assert game.players[1].has_spoken_this_round is False
