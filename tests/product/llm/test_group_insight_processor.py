from types import SimpleNamespace

import pytest

from pallas.product.llm.group_insight_processor import (
    GROUP_INSIGHT_KIND,
    _rebuild_pairs_from_messages,
    _resolve_semantic_bot,
    _sweep_semantic_groups,
    _text,
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

    async def find_recent_in_group(self, group_id, *, before_time=None, before_message_id=None, user_id=None, limit=8):
        # 模拟真实契约：(time, message_id) 复合边界 + 复合排序 + 单页上限 32。
        items = []
        for message in self._messages:
            if before_time is None:
                keep = True
            elif int(message.time) < int(before_time):
                keep = True
            elif before_message_id is not None and int(message.time) == int(before_time):
                keep = int(message.message_id) < int(before_message_id)
            else:
                keep = False
            if keep:
                items.append(message)
        items.sort(key=lambda m: (int(m.time), int(m.message_id)), reverse=True)
        cap = max(1, min(int(limit), 32))
        return list(reversed(items[:cap]))


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
    assert quoted == [("今天好热", "热死我了", "quoted", 11, 11, 2, 1010, False)]
    # bot 自我接话（peer_bot=99 回 real human 的 msg2）作为 self_reflection 候选，is_bot_reply=True。
    assert ("热死我了", "bot插话", "adjacent", 11, 99, 3, 1020, True) in adjacent
    assert ("真的吗", "我也这么觉得", "adjacent", 22, 22, 5, 1040, False) in adjacent


@pytest.mark.asyncio
async def test_rebuild_pairs_marks_bot_self_reply(monkeypatch) -> None:
    from pallas.product.llm import group_insight_processor as mod

    def fake_sender_kind(user_id, *, self_bot_id):
        if user_id == self_bot_id:
            return "self"
        if user_id == 99 or user_id == 501:
            return "peer_bot"
        return "human"

    monkeypatch.setattr(mod, "sender_kind", fake_sender_kind)
    repo = _DummyMessageRepo([
        _msg(1, 11, "今天好热", time=1000),  # human
        _msg(2, 100, "是挺热的", time=1010),  # self bot 接话 (self_bot_id=100)
    ])
    monkeypatch.setattr(mod, "make_message_repository", lambda: repo)

    pairs = await _rebuild_pairs_from_messages(bot_id=100, group_id=42)

    adjacent = [p for p in pairs if p[2] == "adjacent"]
    assert ("今天好热", "是挺热的", "adjacent", 11, 100, 2, 1010, True) in adjacent


@pytest.mark.asyncio
async def test_rebuild_pairs_keeps_candidates_after_persistent_cursor(monkeypatch) -> None:
    from pallas.product.llm import group_insight_processor as mod

    monkeypatch.setattr(mod, "sender_kind", lambda user_id, *, self_bot_id: "human")
    monkeypatch.setattr(
        mod,
        "make_message_repository",
        lambda: _DummyMessageRepo([
            _msg(1, 11, "旧前句", time=1000),
            _msg(2, 12, "旧接话", time=1010),
            _msg(3, 13, "新接话", time=1020),
        ]),
    )

    pairs = await _rebuild_pairs_from_messages(bot_id=100, group_id=42, after_time=1010)

    assert [pair[5] for pair in pairs] == [3]


@pytest.mark.asyncio
async def test_rebuild_pairs_same_second_pagination_does_not_skip(monkeypatch) -> None:
    """同秒超单页（40 条 > 32）：复合游标翻页应覆盖全部消息，不再漏同秒候选。"""
    from pallas.product.llm import group_insight_processor as mod

    monkeypatch.setattr(mod, "sender_kind", lambda user_id, *, self_bot_id: "human")
    messages = [_msg(mid, 11, f"消息{mid}", time=1000) for mid in range(1, 41)]
    monkeypatch.setattr(mod, "make_message_repository", lambda: _DummyMessageRepo(messages))

    pairs = await _rebuild_pairs_from_messages(bot_id=100, group_id=42, limit=64)

    assert {pair[5] for pair in pairs} == set(range(2, 41))


@pytest.mark.asyncio
async def test_rebuild_pairs_same_second_cursor_only_skips_processed_prefix(monkeypatch) -> None:
    """增量游标带 message_id：同秒内已处理前缀之后的候选仍可进入重建。"""
    from pallas.product.llm import group_insight_processor as mod

    monkeypatch.setattr(mod, "sender_kind", lambda user_id, *, self_bot_id: "human")
    monkeypatch.setattr(
        mod,
        "make_message_repository",
        lambda: _DummyMessageRepo([
            _msg(1, 11, "前句", time=1000),
            _msg(2, 12, "接话甲", time=1010),
            _msg(3, 12, "接话乙", time=1010),
            _msg(4, 12, "接话丙", time=1010),
        ]),
    )

    pairs = await _rebuild_pairs_from_messages(bot_id=100, group_id=42, after_time=1010, after_message_id=2)

    assert [pair[5] for pair in pairs] == [3, 4]


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
    monkeypatch.setattr(mod, "_sweep_cursor", 0)

    await _sweep_semantic_groups()

    assert len(enqueued) == 3
    assert {b.payload["group_id"] for b in enqueued} == {42, 7, 8}


@pytest.mark.asyncio
async def test_sweep_semantic_groups_prioritizes_low_sample_count(monkeypatch) -> None:
    from pallas.product.llm import group_insight_processor as mod

    enqueued = []

    class _FakeStore:
        async def enqueue(self, job):
            enqueued.append(job)

    async def fake_list_group_ids(self, bot_id, *, since_time, limit=32):
        return [42, 7, 8] if bot_id == 100 else []

    repo = type("R", (), {"list_recent_group_ids_for_bot": fake_list_group_ids})()
    monkeypatch.setattr(mod, "make_message_repository", lambda: repo)

    async def fake_local_bot_ids():
        return {100}

    monkeypatch.setattr(mod, "_local_bot_ids", fake_local_bot_ids)

    async def fake_resolve(group_id):
        return 1 if group_id > 0 else 0

    async def fake_needs(bot_id, group_id):
        return group_id in (42, 7, 8)

    monkeypatch.setattr(mod, "_resolve_semantic_bot", fake_resolve)
    monkeypatch.setattr(mod, "_group_needs_semantic", fake_needs)
    monkeypatch.setattr(mod, "build_work_job_store", lambda: _FakeStore())
    monkeypatch.setattr(mod, "_sweep_cursor", 0)

    await _sweep_semantic_groups()

    assert [b.payload["group_id"] for b in enqueued] == [7, 8, 42]


@pytest.mark.asyncio
async def test_sweep_semantic_groups_rotates_cursor_across_rounds(monkeypatch) -> None:
    from pallas.product.llm import group_insight_processor as mod

    enqueued = []

    class _FakeStore:
        async def enqueue(self, job):
            enqueued.append(job)

    async def fake_list_group_ids(self, bot_id, *, since_time, limit=32):
        return [1, 2, 3, 4, 5, 6]

    repo = type("R", (), {"list_recent_group_ids_for_bot": fake_list_group_ids})()
    monkeypatch.setattr(mod, "make_message_repository", lambda: repo)

    async def fake_local_bot_ids():
        return {100}

    monkeypatch.setattr(mod, "_local_bot_ids", fake_local_bot_ids)

    async def fake_resolve(gid):
        return 100

    async def fake_needs(*, bot_id, group_id):
        return True

    monkeypatch.setattr(mod, "_resolve_semantic_bot", fake_resolve)
    monkeypatch.setattr(mod, "_group_needs_semantic", fake_needs)
    monkeypatch.setattr(mod, "build_work_job_store", lambda: _FakeStore())
    monkeypatch.setattr(
        "pallas.product.llm.repeater_semantic_style.cached_semantic_style_profile",
        lambda bot_id, group_id, scene: None,
    )
    monkeypatch.setattr(mod, "_SWEEP_BATCH_SIZE", 2)
    monkeypatch.setattr(mod, "_sweep_cursor", 0)

    await _sweep_semantic_groups()
    first_round = [b.payload["group_id"] for b in enqueued]
    assert first_round == [1, 2]

    enqueued.clear()
    monkeypatch.setattr(mod, "_sweep_cursor", 2)
    await _sweep_semantic_groups()
    second_round = [b.payload["group_id"] for b in enqueued]
    assert second_round == [3, 4]

    enqueued.clear()
    monkeypatch.setattr(mod, "_sweep_cursor", 6)
    await _sweep_semantic_groups()
    third_round = [b.payload["group_id"] for b in enqueued]
    assert third_round == [1, 2]


def test_text_replaces_cq_media_with_placeholder() -> None:
    # 图 → [图片]，表情 → [表情]，其它媒体 → [媒体]，并折叠空白、截断到 240。
    assert _text("看看这个  啊 [CQ:image,file=abc.jpg]") == "看看这个 啊 [图片]"
    assert _text("哈哈 [CQ:face,id=6]") == "哈哈 [表情]"
    assert _text("[CQ:flash,id=1] 来了") == "[媒体] 来了"
    assert _text("  多  个   空格  ") == "多 个 空格"
    assert _text("x" * 500) == "x" * 240
