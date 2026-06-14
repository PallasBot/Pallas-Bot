from __future__ import annotations

from src.plugins.who_is_spy.logic import games
from src.plugins.who_is_spy.models import Game, Player
from src.plugins.who_is_spy.session import resolve_game_sync


def test_resolve_game_sync_restores_from_memory() -> None:
    games.clear()
    game = Game(group_id=100, owner_id=1, ready=True)
    game.players[1] = Player(uid=1, nickname="a")
    game.alive_order = [1]
    games[100] = game

    resolved = resolve_game_sync(100)
    assert resolved is game
    games.clear()


def test_resolve_game_sync_prefers_ready_snapshot_over_prep_memory(monkeypatch) -> None:
    from src.plugins.who_is_spy import session as session_mod

    games.clear()
    prep = Game(group_id=200, owner_id=1, ready=False)
    prep.players[1] = Player(uid=1, nickname="房主")
    games[200] = prep

    active = Game(group_id=200, owner_id=1, ready=True)
    active.word_civilian = "苹果"
    active.word_undercover = "梨"
    active.players[1] = Player(uid=1, nickname="房主")
    active.alive_order = [1]

    monkeypatch.setattr(session_mod, "read_active_game_snapshot", lambda _gid: active)

    resolved = resolve_game_sync(200)
    assert resolved is not None
    assert resolved.ready is True
    assert resolved.word_civilian == "苹果"
    assert games[200] is resolved
    games.clear()


def test_resolve_game_sync_ignores_stale_prep_when_session_active(monkeypatch) -> None:
    from src.plugins.who_is_spy import session as session_mod

    games.clear()
    prep = Game(group_id=300, owner_id=1, ready=False)
    prep.players[1] = Player(uid=1, nickname="房主")
    games[300] = prep

    active = Game(group_id=300, owner_id=1, ready=True)
    active.players[1] = Player(uid=1, nickname="房主")
    active.alive_order = [1]

    monkeypatch.setattr(session_mod, "spy_session_active", lambda _gid: True)
    monkeypatch.setattr(session_mod, "read_active_game_snapshot", lambda _gid: active)

    resolved = resolve_game_sync(300)
    assert resolved is not None
    assert resolved.ready is True
    games.clear()
