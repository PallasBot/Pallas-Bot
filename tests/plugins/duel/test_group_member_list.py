from __future__ import annotations

from src.plugins.duel import duel_bots as mod
from src.plugins.duel.duel_bots import list_group_online_bot_ids, parse_group_member_list_user_ids


def test_parse_member_list_dict_data() -> None:
    raw = {"data": [{"user_id": 111}, {"user_id": "222"}]}
    assert parse_group_member_list_user_ids(raw) == {111, 222}


def test_parse_member_list_plain_list() -> None:
    raw = [{"uin": 333}, {"qq": 444}]
    assert parse_group_member_list_user_ids(raw) == {333, 444}


def test_parse_member_list_nested_data_members() -> None:
    raw = {
        "status": "ok",
        "retcode": 0,
        "data": {
            "group_id": 626266902,
            "member_count": 2,
            "members": [{"user_id": "3879348674"}, {"user_id": "923722427"}],
        },
    }
    assert parse_group_member_list_user_ids(raw) == {3879348674, 923722427}


def test_parse_member_list_onebot11_member_list_key() -> None:
    raw = {"group_id": 1, "member_count": 1, "member_list": [{"user_id": 2927116873}]}
    assert parse_group_member_list_user_ids(raw) == {2927116873}


def test_parse_member_list_empty_list() -> None:
    assert parse_group_member_list_user_ids([]) == set()


async def test_shard_empty_member_list_prefers_presence(monkeypatch) -> None:
    mod.clear_group_online_bot_ids_cache()

    class FakeCaller:
        async def get_group_member_list(self, *, group_id: int, no_cache: bool):
            return []

    monkeypatch.setattr("src.platform.shard.context.is_sharding_active", lambda: True)
    monkeypatch.setattr("src.platform.multi_bot.fleet.get_catalog_bot_ids", lambda: frozenset({111, 222, 333}))
    monkeypatch.setattr("src.platform.shard.presence.pick_local_query_bot", lambda: FakeCaller())
    monkeypatch.setattr(
        "src.platform.shard.presence.get_cluster_online_bot_ids",
        lambda: {111, 222, 333},
    )

    ids = await list_group_online_bot_ids(626266902)
    assert ids == [111, 222, 333]


async def test_shard_empty_member_list_skips_fleet_probe(monkeypatch) -> None:
    mod.clear_group_online_bot_ids_cache()
    probe_calls: list[int] = []

    class FakeCaller:
        async def get_group_member_list(self, *, group_id: int, no_cache: bool):
            return []

    async def fake_probe(_caller, group_id: int, catalog):
        probe_calls.append(group_id)
        return []

    monkeypatch.setattr("src.platform.shard.context.is_sharding_active", lambda: True)
    monkeypatch.setattr("src.platform.multi_bot.fleet.get_catalog_bot_ids", lambda: frozenset({111, 222}))
    monkeypatch.setattr("src.platform.shard.presence.pick_local_query_bot", lambda: FakeCaller())
    monkeypatch.setattr(
        "src.platform.shard.presence.get_cluster_online_bot_ids",
        lambda: {111, 222},
    )
    monkeypatch.setattr(mod, "probe_fleet_bots_in_group", fake_probe)

    ids = await list_group_online_bot_ids(626266903)
    assert ids == [111, 222]
    assert probe_calls == []


async def test_list_group_online_bot_ids_uses_cache(monkeypatch) -> None:
    mod.clear_group_online_bot_ids_cache()
    list_calls: list[int] = []

    class FakeCaller:
        async def get_group_member_list(self, *, group_id: int, no_cache: bool):
            list_calls.append(group_id)
            return [{"user_id": 111}, {"user_id": 222}]

    monkeypatch.setattr("src.platform.shard.context.is_sharding_active", lambda: True)
    monkeypatch.setattr("src.platform.multi_bot.fleet.get_catalog_bot_ids", lambda: frozenset({111, 222, 333}))
    monkeypatch.setattr("src.platform.shard.presence.pick_local_query_bot", lambda: FakeCaller())

    first = await list_group_online_bot_ids(626266904)
    second = await list_group_online_bot_ids(626266904)

    assert first == [111, 222]
    assert second == [111, 222]
    assert list_calls == [626266904]


async def test_unified_group_online_bot_ids(monkeypatch) -> None:
    mod.clear_group_online_bot_ids_cache()

    class FakeBot:
        def __init__(self, qq: int) -> None:
            self.self_id = str(qq)

        async def get_group_member_list(self, *, group_id: int, no_cache: bool):
            return [{"user_id": 111}, {"user_id": 222}]

        async def get_group_member_info(self, *, group_id: int, user_id: int, no_cache: bool):
            if user_id not in {111, 222}:
                raise RuntimeError("not in group")

    bots = {str(qq): FakeBot(qq) for qq in (111, 222, 333)}

    monkeypatch.setattr("src.platform.shard.context.is_sharding_active", lambda: False)
    monkeypatch.setattr("src.platform.multi_bot.fleet.get_catalog_bot_ids", lambda: frozenset({111, 222, 333}))
    monkeypatch.setattr(mod, "get_bots", lambda: bots)

    ids = await list_group_online_bot_ids(626266905)
    assert ids == [111, 222]
