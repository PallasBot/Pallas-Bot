from __future__ import annotations

from src.plugins.who_is_spy.logic import current_speaker_id
from src.plugins.who_is_spy.models import Game, Player


def test_current_speaker_follows_alive_order() -> None:
    game = Game(group_id=1, owner_id=10, ready=True)
    game.alive_order = [10, 20, 30]
    game.players = {
        10: Player(uid=10, nickname="a"),
        20: Player(uid=20, nickname="b"),
        30: Player(uid=30, nickname="c"),
    }
    assert current_speaker_id(game) == 10
    game.players[10].has_spoken_this_round = True
    assert current_speaker_id(game) == 20


def test_vote_stats_abstain_line() -> None:
    from src.plugins.who_is_spy.copy import vote_stats_abstain

    assert vote_stats_abstain(2) == "- 弃权：2 票"
