from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

VICTORY_CIVILIAN = "平民方胜。"
VICTORY_UNDERCOVER = "卧底方胜。"


@dataclass
class Player:
    uid: int
    nickname: str
    is_alive: bool = True
    is_undercover: bool = False
    is_blank: bool = False
    has_spoken_this_round: bool = False


def player_role_label(player: Player) -> str:
    if player.is_undercover:
        return "卧底"
    if player.is_blank:
        return "白板"
    return "平民"


@dataclass
class Game:
    group_id: int
    owner_id: int
    ready: bool = False
    word_civilian: str = ""
    word_undercover: str = ""
    players: dict[int, Player] = field(default_factory=dict)
    alive_order: list[int] = field(default_factory=list)
    round_no: int = 0
    votes: dict[int, int | None] = field(default_factory=dict)
    vote_box: dict[int, int] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    expecting_pm_vote: set[int] = field(default_factory=set)
    vote_round_tag: int = 0
    round_speeches: dict[int, str] = field(default_factory=dict)

    def reset_round_flags(self) -> None:
        for player in self.players.values():
            player.has_spoken_this_round = False
        self.round_speeches.clear()
        self.votes.clear()
        self.vote_box.clear()
        self.expecting_pm_vote.clear()
        self.round_no += 1

    def all_alive_have_spoken(self) -> bool:
        alive = self.alive_ids()
        if not alive:
            return False
        return all(self.players[uid].has_spoken_this_round for uid in alive)

    def alive_not_spoken_count(self) -> int:
        return sum(1 for uid in self.alive_ids() if not self.players[uid].has_spoken_this_round)

    def alive_players(self) -> list[Player]:
        return [player for player in self.players.values() if player.is_alive]

    def alive_ids(self) -> list[int]:
        return [player.uid for player in self.alive_players()]

    def undercovers_alive(self) -> int:
        return sum(player.is_alive and player.is_undercover for player in self.players.values())

    def civilians_alive(self) -> int:
        return sum(
            player.is_alive and not player.is_undercover and not player.is_blank for player in self.players.values()
        )

    def blanks_alive(self) -> int:
        return sum(player.is_alive and player.is_blank for player in self.players.values())

    def is_game_over(self) -> str | None:
        undercover_count = self.undercovers_alive()
        civilian_count = self.civilians_alive()
        if undercover_count == 0:
            return VICTORY_CIVILIAN
        if undercover_count >= civilian_count:
            return VICTORY_UNDERCOVER
        return None
