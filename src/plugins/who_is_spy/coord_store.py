"""分片下筹备名册与局内状态落盘（spy_group 协调键）。"""

from __future__ import annotations

import time
from typing import Any

from .group_lock import SPY_GROUP_LOCK
from .models import Game, Player

PREP_PLAYERS_KEY = "prep_players"
GAME_SNAPSHOT_KEY = "game_snapshot"


def prep_players_from_game(game: Game) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for uid in sorted(game.players):
        player = game.players[uid]
        rows.append({"uid": int(player.uid), "nickname": str(player.nickname)})
    return rows


def write_prep_players(group_id: int, game: Game) -> None:
    gid = int(group_id)
    payload = prep_players_from_game(game)

    def stamp(data: dict[str, Any]) -> None:
        data[PREP_PLAYERS_KEY] = payload

    SPY_GROUP_LOCK._mutate(gid, stamp)


def read_prep_players(group_id: int) -> list[tuple[int, str]]:
    data = SPY_GROUP_LOCK.read(int(group_id))
    if not data:
        return []
    raw = data.get(PREP_PLAYERS_KEY)
    if not isinstance(raw, list):
        return []
    out: list[tuple[int, str]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        uid = row.get("uid")
        nick = row.get("nickname")
        if uid is None:
            continue
        try:
            out.append((int(uid), str(nick or uid)))
        except (TypeError, ValueError):
            continue
    return out


def game_to_snapshot(game: Game) -> dict[str, Any]:
    return {
        "group_id": int(game.group_id),
        "owner_id": int(game.owner_id),
        "ready": bool(game.ready),
        "word_civilian": game.word_civilian,
        "word_undercover": game.word_undercover,
        "round_no": int(game.round_no),
        "vote_round_tag": int(game.vote_round_tag),
        "alive_order": [int(uid) for uid in game.alive_order],
        "expecting_pm_vote": [int(uid) for uid in game.expecting_pm_vote],
        "votes": {str(uid): vote for uid, vote in game.votes.items()},
        "vote_box": {str(uid): count for uid, count in game.vote_box.items()},
        "round_speeches": {str(uid): text for uid, text in game.round_speeches.items()},
        "players": [
            {
                "uid": int(player.uid),
                "nickname": str(player.nickname),
                "is_alive": bool(player.is_alive),
                "is_undercover": bool(player.is_undercover),
                "is_blank": bool(player.is_blank),
                "has_spoken_this_round": bool(player.has_spoken_this_round),
            }
            for player in game.players.values()
        ],
    }


def game_from_snapshot(raw: dict[str, Any]) -> Game | None:
    try:
        group_id = int(raw["group_id"])
        owner_id = int(raw["owner_id"])
    except (KeyError, TypeError, ValueError):
        return None

    game = Game(group_id=group_id, owner_id=owner_id)
    game.ready = bool(raw.get("ready"))
    game.word_civilian = str(raw.get("word_civilian") or "")
    game.word_undercover = str(raw.get("word_undercover") or "")
    game.round_no = int(raw.get("round_no") or 0)
    game.vote_round_tag = int(raw.get("vote_round_tag") or 0)

    alive_raw = raw.get("alive_order")
    if isinstance(alive_raw, list):
        game.alive_order = [int(uid) for uid in alive_raw]

    vote_raw = raw.get("expecting_pm_vote")
    if isinstance(vote_raw, list):
        game.expecting_pm_vote = {int(uid) for uid in vote_raw}

    votes_raw = raw.get("votes")
    if isinstance(votes_raw, dict):
        for key, value in votes_raw.items():
            try:
                uid = int(key)
            except (TypeError, ValueError):
                continue
            if value is None:
                game.votes[uid] = None
            else:
                game.votes[uid] = int(value)

    box_raw = raw.get("vote_box")
    if isinstance(box_raw, dict):
        for key, value in box_raw.items():
            try:
                game.vote_box[int(key)] = int(value)
            except (TypeError, ValueError):
                continue

    speeches_raw = raw.get("round_speeches")
    if isinstance(speeches_raw, dict):
        for key, value in speeches_raw.items():
            try:
                uid = int(key)
            except (TypeError, ValueError):
                continue
            text = str(value or "").strip()
            if text:
                game.round_speeches[uid] = text

    players_raw = raw.get("players")
    if isinstance(players_raw, list):
        for row in players_raw:
            if not isinstance(row, dict):
                continue
            try:
                uid = int(row["uid"])
            except (KeyError, TypeError, ValueError):
                continue
            game.players[uid] = Player(
                uid=uid,
                nickname=str(row.get("nickname") or uid),
                is_alive=bool(row.get("is_alive", True)),
                is_undercover=bool(row.get("is_undercover")),
                is_blank=bool(row.get("is_blank")),
                has_spoken_this_round=bool(row.get("has_spoken_this_round")),
            )

    if not game.players:
        return None
    return game


def write_game_snapshot(game: Game) -> None:
    gid = int(game.group_id)
    payload = game_to_snapshot(game)

    def stamp(data: dict[str, Any]) -> None:
        data[GAME_SNAPSHOT_KEY] = payload
        if game.ready:
            now = time.time()
            data["session_active"] = True
            data["session_until"] = now + SPY_GROUP_LOCK.busy_ttl_sec

    SPY_GROUP_LOCK._mutate(gid, stamp)


def read_game_snapshot(group_id: int) -> Game | None:
    data = SPY_GROUP_LOCK.read(int(group_id))
    if not data:
        return None
    raw = data.get(GAME_SNAPSHOT_KEY)
    if not isinstance(raw, dict):
        return None
    return game_from_snapshot(raw)


def clear_game_snapshot(group_id: int) -> None:
    gid = int(group_id)

    def stamp(data: dict[str, Any]) -> None:
        data.pop(GAME_SNAPSHOT_KEY, None)

    SPY_GROUP_LOCK._mutate(gid, stamp)
