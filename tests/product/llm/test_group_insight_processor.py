from types import SimpleNamespace

import pytest

from pallas.product.llm.group_insight_processor import (
    GROUP_INSIGHT_KIND,
    _rebuild_pairs_from_messages,
    _resolve_semantic_bot,
    _sweep_semantic_groups,
    build_semantic_insight_job,
    handle_group_insight,
)


def _msg(message_id, user_id, plain_text, *, time=1000, bot_id=0, reply_to_message_id=0):
    return SimpleNamespace(
        message_id=message_id,
        user_id=user_id,
        bot_id=bot_id,
        plain_text=plain_text,
        raw_message=plain_text,
        time=time,
        reply_to_message_id=reply_to_message_id,
    )


class _DummyMessageRepo:
    def __init__(self, messages):
        self._messages = messages

    async def find_recent_in_group(self, group_id, *, before_time=None, user_id=None, limit=8):
        return list(self._messages)


@pytest.mark.asyncio
async def test_rebuild_pairs_picks_quoted_pair_and_human_adjacent(monkeypatch) -> None:
    from pallas.product.llm import group_insight_processor as mod

    calls = []

    def fake_sender_kind(user_id, *, self_bot_id):
        calls.append((user_id, self_bot_id))
        if user_id == 99 or user_id == 501:
            return "peer_bot"
        return "human"

    monkeypatch.setattr(mod, "sender_kind", fake_sender_kind)
    repo = _DummyMessageRepo([
        _msg(1, 11, "今天好热", time=1000),  # human
        _msg(2, 11, "热死我了", time=1010, reply_to_message_id=1),  # quoted reply
        _msg(3, 99, "bot插话", time=1020),  # peer_bot
        _msg(4, 22, "真的吗", time=1030, reply_to_message_id=3),  # reply to peer_bot -> 引用对里trigger非human
        _msg(5, 22, "我也这么觉得", time=1040),  # adjacent human (predecessor=4 human)
    ])
    monkeypatch.setattr(mod, "make_message_repository", lambda: repo)

    pairs = await _rebuild_pairs_from_messages(bot_id=100, group_id=42)

    quoted = [p for p in pairs if p[2] == "quoted"]
    adjacent = [p for p in pairs if p[2] == "adjacent"]
    assert quoted == [("今天好热", "热死我了", "quoted", 11, 11, 2, 1010)]
    assert adjacent == [("真的吗", "我也这么觉得", "adjacent", 22, 22, 5, 1040)]


@pytest.mark.asyncio
async def test_handle_group_insight_dispatches_semantic_task(monkeypatch) -> None:
    from pallas.product.llm import group_insight_processor as mod

    async def fake_semantic(payload):
        assert payload["task"] == "semantic"
        assert payload["bot_id"] == 100
        assert payload["group_id"] == 42

    async def fake_style(payload):
        raise AssertionError("style_profile should not be invoked for semantic task")

    monkeypatch.setattr(mod, "_produce_semantic_profile", fake_semantic)
    monkeypatch.setattr(mod, "_compute_group_style_profile", fake_style)

    result = await handle_group_insight({"task": "semantic", "bot_id": 100, "group_id": 42})
    assert result is None


@pytest.mark.asyncio
async def test_handle_group_insight_dispatch_style_profile_task(monkeypatch) -> None:
    from pallas.product.llm import group_insight_processor as mod

    async def fake_style(payload):
        assert payload["task"] == "style_profile"
        assert payload["group_id"] == 42

    async def fake_semantic(payload):
        raise AssertionError("semantic should not be invoked for style_profile task")

    monkeypatch.setattr(mod, "_produce_semantic_profile", fake_semantic)
    monkeypatch.setattr(mod, "_compute_group_style_profile", fake_style)

    result = await handle_group_insight({"task": "style_profile", "group_id": 42})
    assert result is None


@pytest.mark.asyncio
async def test_handle_group_insight_ignores_unknown_task(monkeypatch) -> None:
    from pallas.product.llm import group_insight_processor as mod

    async def fake_style(payload):
        raise AssertionError("should not dispatch unknown task")

    monkeypatch.setattr(mod, "_produce_semantic_profile", fake_style)
    monkeypatch.setattr(mod, "_compute_group_style_profile", fake_style)

    result = await handle_group_insight({"task": "unknown"})
    assert result is None


def test_build_semantic_insight_job_uses_stable_idempotency_key() -> None:
    job = build_semantic_insight_job(bot_id=100, group_id=42, day=20000)
    assert job.kind == GROUP_INSIGHT_KIND
    assert job.payload["task"] == "semantic"
    assert job.idempotency_key == "group.insight:semantic:100:42:20000"


@pytest.mark.asyncio
async def test_resolve_semantic_bot_prefers_configured_bot(monkeypatch) -> None:
    from pallas.product.llm import group_insight_processor as mod

    class _FakeStorage:
        async def get(self, key):
            assert key == "semantic_style_bot_id"
            return "777"

    async def fake_list(self, group_id, *, since_time, limit=32):
        return []

    repo = type("R", (), {"list_recent_bot_ids_for_group": fake_list})()
    monkeypatch.setattr(mod, "make_message_repository", lambda: repo)
    monkeypatch.setattr("pallas.core.storage.store.GroupPluginStorage", lambda plugin, gid: _FakeStorage())

    assert await _resolve_semantic_bot(42) == 777


@pytest.mark.asyncio
async def test_resolve_semantic_bot_falls_back_to_min_catalog_bot(monkeypatch) -> None:
    from pallas.product.llm import group_insight_processor as mod

    class _FakeStorage:
        async def get(self, key):
            return None

    async def fake_list(self, group_id, *, since_time, limit=32):
        return [333, 100, 222]

    repo = type("R", (), {"list_recent_bot_ids_for_group": fake_list})()
    monkeypatch.setattr(mod, "make_message_repository", lambda: repo)
    monkeypatch.setattr("pallas.core.storage.store.GroupPluginStorage", lambda plugin, gid: _FakeStorage())
    monkeypatch.setattr("pallas.core.platform.multi_bot.fleet.get_catalog_bot_ids", lambda: {222, 333, 999})

    assert await _resolve_semantic_bot(42) == 222


@pytest.mark.asyncio
async def test_resolve_semantic_bot_returns_zero_without_catalog_bot(monkeypatch) -> None:
    from pallas.product.llm import group_insight_processor as mod

    class _FakeStorage:
        async def get(self, key):
            return None

    async def fake_list(self, group_id, *, since_time, limit=32):
        return [333, 100]

    repo = type("R", (), {"list_recent_bot_ids_for_group": fake_list})()
    monkeypatch.setattr(mod, "make_message_repository", lambda: repo)
    monkeypatch.setattr("pallas.core.storage.store.GroupPluginStorage", lambda plugin, gid: _FakeStorage())
    monkeypatch.setattr("pallas.core.platform.multi_bot.fleet.get_catalog_bot_ids", lambda: {999})

    assert await _resolve_semantic_bot(42) == 0


@pytest.mark.asyncio
async def test_sweep_semantic_groups_dedups_groups_and_skips_needed_check(monkeypatch) -> None:
    from pallas.product.llm import group_insight_processor as mod

    enqueued = []

    class _FakeStore:
        async def enqueue(self, job):
            enqueued.append(job)

    async def fake_list_group_ids(self, bot_id, *, since_time, limit=32):
        return [42, 7] if bot_id == 100 else [7, 8]

    repo = type("R", (), {"list_recent_group_ids_for_bot": fake_list_group_ids})()
    monkeypatch.setattr(mod, "make_message_repository", lambda: repo)

    async def fake_local_bot_ids():
        return {100, 200}

    monkeypatch.setattr(mod, "_local_bot_ids", fake_local_bot_ids)

    async def fake_resolve(group_id):
        return {42: 100, 7: 200, 8: 300}.get(group_id, 0)

    async def fake_needs(bot_id, group_id):
        return group_id in (42, 7, 8) and bot_id > 0

    monkeypatch.setattr(mod, "_resolve_semantic_bot", fake_resolve)
    monkeypatch.setattr(mod, "_group_needs_semantic", fake_needs)
    monkeypatch.setattr(mod, "build_work_job_store", lambda: _FakeStore())

    await _sweep_semantic_groups()

    assert len(enqueued) == 3
    assert {b.payload["group_id"] for b in enqueued} == {42, 7, 8}
