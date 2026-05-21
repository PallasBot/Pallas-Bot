from __future__ import annotations

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
    class FakeCaller:
        async def get_group_member_list(self, *, group_id: int, no_cache: bool):
            return []

    monkeypatch.setattr("src.common.shard.registry.config.is_sharding_active", lambda: True)
    monkeypatch.setattr("src.common.multi_bot.fleet.get_catalog_bot_ids", lambda: frozenset({111, 222, 333}))
    monkeypatch.setattr("src.common.shard.presence.pick_local_query_bot", lambda: FakeCaller())
    monkeypatch.setattr(
        "src.common.shard.presence.get_cluster_online_bot_ids",
        lambda: {111, 222, 333},
    )

    ids = await list_group_online_bot_ids(626266902)
    assert ids == [111, 222, 333]
