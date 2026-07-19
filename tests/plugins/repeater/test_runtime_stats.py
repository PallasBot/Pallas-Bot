from __future__ import annotations

from collections import deque
from types import SimpleNamespace

from packages.repeater.message_store import MessageStore
from packages.repeater.model import Chat


def test_repeater_runtime_cache_snapshot_counts_records() -> None:
    from packages.repeater.runtime_stats import repeater_runtime_cache_snapshot

    MessageStore._message_dict.clear()
    Chat._reply_dict.clear()
    Chat._recent_topics.clear()

    MessageStore._message_dict[100] = [object(), object(), object()]
    MessageStore._message_dict[200] = [object()]

    Chat._reply_dict[100][1] = [{"reply": "a"}, {"reply": "b"}]
    Chat._reply_dict[100][2] = [{"reply": "c"}]
    Chat._reply_dict[300][3] = [{"reply": "d"}]

    Chat._recent_topics[100] = deque(["x", "y"], maxlen=16)
    Chat._recent_topics[200] = deque(["z"], maxlen=16)

    snap = repeater_runtime_cache_snapshot()

    assert snap["message_groups"] == 2
    assert snap["message_records"] == 4
    assert snap["message_max_group_records"] == 3
    assert snap["reply_groups"] == 2
    assert snap["reply_bot_buckets"] == 3
    assert snap["reply_records"] == 4
    assert snap["reply_max_bucket_records"] == 2
    assert snap["recent_topics_groups"] == 2
    assert snap["recent_topics_records"] == 3
    assert snap["top_message_groups"][0] == {"group_id": 100, "records": 3}
    assert snap["top_reply_groups"][0] == {"group_id": 100, "records": 3, "bot_buckets": 2}


async def test_prune_repeater_runtime_caches_drops_stale_groups() -> None:
    from packages.repeater.runtime_stats import prune_repeater_runtime_caches

    MessageStore._message_dict.clear()
    Chat._reply_dict.clear()
    Chat._recent_topics.clear()

    MessageStore._message_dict[100] = [SimpleNamespace(time=50), SimpleNamespace(time=60)]
    MessageStore._message_dict[200] = [SimpleNamespace(time=700)]

    Chat._reply_dict[100][1] = [{"time": 70, "reply": "old"}]
    Chat._reply_dict[200][2] = [{"time": 710, "reply": "new"}]
    Chat._reply_dict[300][3] = []

    Chat._recent_topics[100] = deque(["old"], maxlen=16)
    Chat._recent_topics[200] = deque(["new"], maxlen=16)
    Chat._recent_topics[300] = deque(["dangling"], maxlen=16)

    result = await prune_repeater_runtime_caches(now=1000, ttl_sec=400)

    assert result == {
        "message_groups_removed": 1,
        "message_records_removed": 2,
        "reply_groups_removed": 2,
        "reply_bot_buckets_removed": 2,
        "reply_records_removed": 1,
        "recent_topics_groups_removed": 2,
    }
    assert sorted(MessageStore._message_dict) == [200]
    assert sorted(Chat._reply_dict) == [200]
    assert sorted(Chat._recent_topics) == [200]
