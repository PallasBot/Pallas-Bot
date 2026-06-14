from __future__ import annotations

from src.plugins.who_is_spy.logic import assign_roles, player_role_word
from src.plugins.who_is_spy.models import Game, Player


def test_assign_roles_can_deal_blank_card(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.plugins.who_is_spy.logic.pick_words",
        lambda group_id, avoid_recent=0: ("可乐", "雪碧"),
    )
    game = Game(group_id=1, owner_id=10)
    for uid in (10, 20, 30, 40):
        game.players[uid] = Player(uid=uid, nickname=str(uid))

    assign_roles(game, undercover_count=1, blank_count=1, avoid_recent=0)

    roles = {uid: (game.players[uid].is_undercover, game.players[uid].is_blank) for uid in game.players}
    assert sum(1 for undercover, blank in roles.values() if undercover) == 1
    assert sum(1 for undercover, blank in roles.values() if blank) == 1
    assert sum(1 for undercover, blank in roles.values() if not undercover and not blank) == 2

    blank_player = next(player for player in game.players.values() if player.is_blank)
    assert player_role_word(game, blank_player) == ("白板", "")
