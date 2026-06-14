from __future__ import annotations

from src.plugins.who_is_spy.models import VICTORY_CIVILIAN, VICTORY_UNDERCOVER, Game, Player


def test_blank_not_counted_as_civilian_for_win() -> None:
    game = Game(group_id=1, owner_id=1, ready=True)
    game.players = {
        1: Player(uid=1, nickname="卧", is_undercover=True),
        2: Player(uid=2, nickname="平"),
        3: Player(uid=3, nickname="白", is_blank=True),
    }
    assert game.civilians_alive() == 1
    assert game.blanks_alive() == 1
    assert game.is_game_over() == VICTORY_UNDERCOVER

    game.players[1].is_alive = False
    assert game.is_game_over() == VICTORY_CIVILIAN


def test_all_undercovers_out_civilian_wins_with_blank_alive() -> None:
    game = Game(group_id=1, owner_id=1, ready=True)
    game.players = {
        1: Player(uid=1, nickname="卧", is_undercover=True, is_alive=False),
        2: Player(uid=2, nickname="平"),
        3: Player(uid=3, nickname="白", is_blank=True),
    }
    assert game.is_game_over() == VICTORY_CIVILIAN
