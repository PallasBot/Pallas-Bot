import time
from collections import defaultdict


class Player:
    """玩家缓存对象，绑定群组和超时时间"""

    __slots__ = ("group_id", "user_id", "expire_time", "_timeout")

    def __init__(self, group_id: int, user_id: int, timeout: int = 300):
        self.group_id = group_id
        self.user_id = user_id
        self._timeout = timeout
        self.expire_time = time.time() + timeout

    def is_expired(self) -> bool:
        return time.time() > self.expire_time

    def refresh(self) -> None:
        self.expire_time = time.time() + self._timeout

    def match(self, user_id: int, group_id: int) -> bool:
        return self.user_id == user_id and self.group_id == group_id


class PlayerList:
    """玩家列表容器，按群隔离，自动超时清理"""

    def __init__(self, timeout: int = 300):
        self.timeout = timeout
        self._players: dict[int, list[Player]] = defaultdict(list)

    def _get_players(self, group_id: int) -> list[Player]:
        self._players[group_id] = [p for p in self._players[group_id] if not p.is_expired()]
        return self._players[group_id]

    def append(self, user_id: int, group_id: int) -> None:
        players = self._get_players(group_id)
        if not any(p.match(user_id, group_id) for p in players):
            players.append(Player(group_id, user_id, self.timeout))

    def find_and_refresh(self, user_id: int, group_id: int) -> bool:
        """查找玩家并刷新超时，返回是否找到"""
        for p in self._get_players(group_id):
            if p.match(user_id, group_id):
                p.refresh()
                return True
        return False

    def contains(self, user_id: int, group_id: int) -> bool:
        return any(p.match(user_id, group_id) for p in self._get_players(group_id))

    def clear(self, group_id: int) -> None:
        self._players[group_id] = []

    def get_user_ids(self, group_id: int) -> list[int]:
        return [p.user_id for p in self._get_players(group_id)]

    def remove(self, user_id: int, group_id: int) -> bool:
        players = self._players[group_id]
        for p in players:
            if p.match(user_id, group_id):
                players.remove(p)
                return True
        return False
