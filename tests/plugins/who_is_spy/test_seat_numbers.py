from __future__ import annotations

from src.plugins.who_is_spy.logic import assign_roles, build_index_map, render_alive_numbered
from src.plugins.who_is_spy.models import Game, Player


def test_seat_numbers_stable_after_elimination() -> None:
    game = Game(group_id=1, owner_id=10, ready=True)
    for uid, nick in ((10, "甲"), (20, "乙"), (30, "丙"), (40, "丁")):
        game.players[uid] = Player(uid=uid, nickname=nick)
    game.alive_order = [30, 10, 40, 20]

    assert build_index_map(game) == {1: 30, 2: 10, 3: 40, 4: 20}
    assert render_alive_numbered(game) == "1. 丙\n2. 甲\n3. 丁\n4. 乙"

    game.players[40].is_alive = False

    assert build_index_map(game) == {1: 30, 2: 10, 4: 20}
    assert render_alive_numbered(game) == "1. 丙\n2. 甲\n4. 乙"


def test_assign_roles_shuffles_seat_order(monkeypatch) -> None:
    game = Game(group_id=1, owner_id=10)
    for uid in (10, 20, 30, 40):
        game.players[uid] = Player(uid=uid, nickname=str(uid))

    shuffles = [[40, 20, 10, 30], [10, 30, 20, 40], [30, 10, 40, 20], [40, 10, 30, 20]]
    call = 0

    def fake_shuffle(items: list[int]) -> None:
        nonlocal call
        items[:] = shuffles[call]
        call += 1

    monkeypatch.setattr("src.plugins.who_is_spy.logic.random.shuffle", fake_shuffle)

    assign_roles(game, undercover_count=1, blank_count=0, avoid_recent=0)
    first = list(game.alive_order)
    assert build_index_map(game)[1] == 10

    game.players = {uid: Player(uid=uid, nickname=str(uid)) for uid in (10, 20, 30, 40)}
    assign_roles(game, undercover_count=1, blank_count=0, avoid_recent=0)
    second = list(game.alive_order)
    assert build_index_map(game)[1] == 40
    assert first != second
