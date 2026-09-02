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

    def fake_is_peer_bot(user_id):
        return user_id == 99 or user_id == 501

    monkeypatch.setattr("pallas.product.llm.sender_identity.is_peer_bot", fake_is_peer_bot)
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

    monkeypatch.setattr("pallas.product.llm.sender_identity.is_peer_bot", lambda user_id: user_id in (99, 501))
    repo = _DummyMessageRepo([
        _msg(1, 11, "今天好热", time=1000),  # human
        _msg(2, 100, "是挺热的", time=1010),  # self bot 接话 (self_bot_id=100)
    ])
    monkeypatch.setattr(mod, "make_message_repository", lambda: repo)

    pairs = await _rebuild_pairs_from_messages(bot_id=100, group_id=42)

    adjacent = [p for p in pairs if p[2] == "adjacent"]
    assert ("今天好热", "是挺热的", "adjacent", 11, 100, 2, 1010, True) in adjacent


@pytest.mark.asyncio
async def test_rebuild_pairs_known_bots_covers_peer_detection_gap(monkeypatch) -> None:
    """work aux 进程不连接 QQ，is_peer_bot 恒 False；known_bots（message 表推导）
    必须仍能把协作 bot 消息标记为 bot 回复，而不是混入真人接话参考。"""
    from pallas.product.llm import group_insight_processor as mod

    monkeypatch.setattr("pallas.product.llm.sender_identity.is_peer_bot", lambda user_id: False)
    repo = _DummyMessageRepo([
        _msg(1, 11, "今天好热", time=1000),  # human
        _msg(2, 99, "bot插话", time=1010),  # 协作 bot（不在 peer 列表，但 known_bots 里有）
        _msg(3, 22, "真的吗", time=1020),  # human
    ])
    monkeypatch.setattr(mod, "make_message_repository", lambda: repo)

    pairs = await _rebuild_pairs_from_messages(bot_id=100, group_id=42, known_bots={99})

    adjacent = [p for p in pairs if p[2] == "adjacent"]
    # bot 接话标记 is_bot_reply=True（self_reflection 候选），不进入真人 direct_pairs
    assert ("今天好热", "bot插话", "adjacent", 11, 99, 2, 1010, True) in adjacent
    # 真人接话仍正常：bot 消息不在真人序列，msg3 的前驱是 msg1
    assert ("今天好热", "真的吗", "adjacent", 11, 22, 3, 1020, False) in adjacent


@pytest.mark.asyncio
async def test_rebuild_pairs_keeps_candidates_after_persistent_cursor(monkeypatch) -> None:
    from pallas.product.llm import group_insight_processor as mod

    monkeypatch.setattr("pallas.product.llm.sender_identity.is_peer_bot", lambda user_id: False)
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

    monkeypatch.setattr("pallas.product.llm.sender_identity.is_peer_bot", lambda user_id: False)
    messages = [_msg(mid, 11, f"消息{mid}", time=1000) for mid in range(1, 41)]
    monkeypatch.setattr(mod, "make_message_repository", lambda: _DummyMessageRepo(messages))

    pairs = await _rebuild_pairs_from_messages(bot_id=100, group_id=42, limit=64)

    assert {pair[5] for pair in pairs} == set(range(2, 41))


@pytest.mark.asyncio
async def test_rebuild_pairs_same_second_cursor_only_skips_processed_prefix(monkeypatch) -> None:
    """增量游标带 message_id：同秒内已处理前缀之后的候选仍可进入重建。"""
    from pallas.product.llm import group_insight_processor as mod

    monkeypatch.setattr("pallas.product.llm.sender_identity.is_peer_bot", lambda user_id: False)
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
async def test_rebuild_pairs_prefers_quoted_over_adjacent(monkeypatch) -> None:
    """quoted 样本可接受率远高于 adjacent，limit 不足时不得被时间靠前的 adjacent 挤出。"""
    from pallas.product.llm import group_insight_processor as mod

    monkeypatch.setattr("pallas.product.llm.sender_identity.is_peer_bot", lambda user_id: False)
    monkeypatch.setattr(
        mod,
        "make_message_repository",
        lambda: _DummyMessageRepo([
            _msg(1, 11, "相邻前句一", time=1000),
            _msg(2, 12, "相邻接话一", time=1005),
            _msg(3, 11, "相邻前句二", time=1010),
            _msg(4, 12, "相邻接话二", time=1015),
            _msg(5, 11, "引用前句", time=1020),
            _msg(6, 12, "引用接话", time=1025, reply_to_message_id=5),
        ]),
    )

    pairs = await _rebuild_pairs_from_messages(bot_id=100, group_id=42, limit=2)

    assert [pair[2] for pair in pairs] == ["quoted", "adjacent"]
    assert [pair[5] for pair in pairs] == [6, 2]


@pytest.mark.asyncio
async def test_rebuild_pairs_skips_pure_media_reply_keeps_face(monkeypatch) -> None:
    """接话端只剩图片/媒体占位（无文字）不送标注；表情回复是真实接话，保留。"""
    from pallas.product.llm import group_insight_processor as mod

    monkeypatch.setattr("pallas.product.llm.sender_identity.is_peer_bot", lambda user_id: False)
    monkeypatch.setattr(
        mod,
        "make_message_repository",
        lambda: _DummyMessageRepo([
            _msg(1, 11, "看图", time=1000),
            _msg(2, 12, "[CQ:image,file=abc.jpg]", time=1005, reply_to_message_id=1),
            _msg(3, 12, "哈这个词好怪", time=1010, reply_to_message_id=1),
            _msg(4, 12, "[CQ:face,id=6]", time=1015),
            _msg(5, 12, "[CQ:image,file=a.png][CQ:record,url=b]", time=1020),
        ]),
    )

    pairs = await _rebuild_pairs_from_messages(bot_id=100, group_id=42)

    reply_ids = [pair[5] for pair in pairs]
    assert 2 not in reply_ids
    assert 3 in reply_ids
    assert 4 in reply_ids


@pytest.mark.asyncio
async def test_rebuild_pairs_rejects_punctuation_adjacent_without_heat(monkeypatch) -> None:
    """无复读热度的纯标点 adjacent 不应进入 LLM 候选。"""
    from pallas.product.llm import group_insight_processor as mod

    monkeypatch.setattr("pallas.product.llm.sender_identity.is_peer_bot", lambda user_id: False)

    async def fake_heat(**kwargs):
        return {}

    monkeypatch.setattr(mod, "_repeater_answer_heat", fake_heat)
    monkeypatch.setattr(
        mod,
        "make_message_repository",
        lambda: _DummyMessageRepo([
            _msg(1, 11, "今天的部署状态", time=1000),
            _msg(2, 12, "...", time=1005),
        ]),
    )

    pairs = await _rebuild_pairs_from_messages(bot_id=100, group_id=42)

    assert pairs == []


@pytest.mark.asyncio
async def test_rebuild_pairs_keeps_unrelated_adjacent_with_repeater_heat(monkeypatch) -> None:
    """已有复读热度的 adjacent 即使字面无关，也应保留给语义层复核。"""
    from pallas.product.llm import group_insight_processor as mod

    monkeypatch.setattr("pallas.product.llm.sender_identity.is_peer_bot", lambda user_id: False)

    async def fake_heat(**kwargs):
        return {("今天的部署状态", "我在吃饭呢"): 3}

    monkeypatch.setattr(mod, "_repeater_answer_heat", fake_heat)
    monkeypatch.setattr(
        mod,
        "make_message_repository",
        lambda: _DummyMessageRepo([
            _msg(1, 11, "今天的部署状态", time=1000),
            _msg(2, 12, "我在吃饭呢", time=1005),
        ]),
    )

    pairs = await _rebuild_pairs_from_messages(bot_id=100, group_id=42)

    assert [pair[5] for pair in pairs] == [2]


@pytest.mark.asyncio
async def test_rebuild_pairs_ranks_adjacent_by_similarity_then_repeater_heat(monkeypatch) -> None:
    """adjacent 排序：先按复读 answer 真人接话热度（C），再按文本相似度（A），均零 LLM。"""
    from pallas.product.llm import group_insight_processor as mod

    monkeypatch.setattr("pallas.product.llm.sender_identity.is_peer_bot", lambda user_id: user_id == 99)

    async def fake_heat(*, bot_id, group_id):
        return {
            ("牛牛今天好可爱", "确实可爱"): 2,
            ("再换个话题随便聊", "也是无关回复"): 1,
        }

    monkeypatch.setattr(mod, "_repeater_answer_heat", fake_heat)
    monkeypatch.setattr(
        mod,
        "make_message_repository",
        lambda: _DummyMessageRepo([
            _msg(1, 11, "牛牛今天好可爱", time=1000),
            _msg(2, 11, "牛牛今天好可爱", time=1001),
            _msg(3, 12, "确实可爱", time=1005),  # 热度 2（trigger=时间线上前一条真人 msg2）
            _msg(4, 99, "系统状态正常", time=1010),  # bot/peer 消息：作 bot 接话 pair，但相似度 0 且无热度
            _msg(5, 12, "完全无关的一句话", time=1015),
            _msg(6, 11, "再换个话题随便聊", time=1020),
            _msg(7, 12, "也是无关回复", time=1025),
        ]),
    )

    pairs = await _rebuild_pairs_from_messages(bot_id=100, group_id=42, limit=2)

    # pair3 热度 2、pair7 热度 1 均排前；无热度的 pair4/pair5 被挤出 limit=2。
    assert [pair[5] for pair in pairs] == [3, 7]


@pytest.mark.asyncio
async def test_rebuild_pairs_prefers_similarity_within_same_heat(monkeypatch) -> None:
    """同为无热度时，trigger/reply 文本相似度高的 adjacent 排前（quoted 仍在最前）。"""
    from pallas.product.llm import group_insight_processor as mod

    monkeypatch.setattr("pallas.product.llm.sender_identity.is_peer_bot", lambda user_id: False)
    monkeypatch.setattr("pallas.core.foundation.db.make_local_context_repository", lambda: None)
    monkeypatch.setattr(
        mod,
        "make_message_repository",
        lambda: _DummyMessageRepo([
            # 真人序列 msg1/msg3/msg5 交错接话 msg2/msg4/msg6；每个 adjacent 的 trigger 是
            # 时间线上前一条真人消息，故用成对近义文本控制相似度差异。
            _msg(1, 11, "低相关的开头白", time=1000),
            _msg(2, 12, " [*] 完全无关", time=1010),
            _msg(3, 11, "这个副本机制太复杂了", time=1020),
            _msg(4, 12, "这个机制好难懂啊", time=1030),  # 与 msg3 相似度高
            _msg(5, 11, "引用源", time=1040),
            _msg(6, 12, "引用接话", time=1050, reply_to_message_id=5),
        ]),
    )

    pairs = await _rebuild_pairs_from_messages(bot_id=100, group_id=42, limit=3)

    assert [pair[2] for pair in pairs] == ["quoted", "adjacent", "adjacent"]
    assert [pair[5] for pair in pairs] == [6, 4, 2]


@pytest.mark.asyncio
async def test_repeater_answer_heat_builds_pair_counts_from_context_repository(monkeypatch) -> None:
    """C 链路：answer 热度表从 context 仓库读取（零 LLM），按 (trigger, reply) 聚合最大 count。"""
    from pallas.product.llm import group_insight_processor as mod

    class _DummyContextRepo:
        async def list_answers_for_group_since(self, group_id, cutoff_time):
            assert int(group_id) == 42
            assert int(cutoff_time) > 0
            return [
                SimpleNamespace(keywords="牛牛今天好可爱", count=3, messages=["确实可爱", ""]),
                SimpleNamespace(keywords="", count=2, messages=["空触发忽略"]),
                SimpleNamespace(keywords="换个前句", count=1, messages=["低热度回复"]),
            ]

    monkeypatch.setattr("pallas.core.foundation.db.make_local_context_repository", lambda: _DummyContextRepo())

    heat = await mod._repeater_answer_heat(bot_id=100, group_id=42)

    # 空触发忽略；每条 answer 以最大 count 记一次「trigger→reply」热度。
    assert heat[("牛牛今天好可爱", "确实可爱")] == 3
    assert heat[("换个前句", "低热度回复")] == 1
    assert all(reply != "空触发忽略" for _, reply in heat)


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


@pytest.mark.asyncio
async def test_produce_semantic_profile_partial_failure_persists_and_advances(monkeypatch) -> None:
    from pallas.product.llm import group_insight_processor as mod
    from pallas.product.llm import repeater_semantic_style as sem

    pairs = [
        ("前句1", "接话1", "adjacent", 11, 12, 101, 1000, False),
        ("前句2", "接话2", "adjacent", 13, 14, 102, 1100, False),
        ("前句3", "接话3", "adjacent", 15, 16, 103, 1200, False),
    ]
    good_label = sem.SemanticStyleLabel(is_reply_pair=True, transferable=True)
    persisted: list[sem.SemanticStyleExample] = []
    marked: list[tuple[int, int, int, int]] = []

    async def fake_rebuild(**kwargs):
        return pairs

    async def fake_known_bots(group_id):
        return set()

    monkeypatch.setattr(mod, "_known_bots_in_group", fake_known_bots)
    monkeypatch.setattr(mod, "_rebuild_pairs_from_messages", fake_rebuild)
    monkeypatch.setattr(sem, "semantic_style_collection_enabled", lambda *, bot_id, group_id: True)
    monkeypatch.setattr(sem, "semantic_label_budget_ok", lambda: True)
    monkeypatch.setattr(sem, "get_semantic_style_group_cursor", lambda *, bot_id, group_id: (0, 0))
    monkeypatch.setattr(sem, "labeled_semantic_style_reply_ids", lambda bot_id, group_id: set())

    async def fake_batch(items):
        return [(good_label, None), None, (good_label, None)]

    monkeypatch.setattr(sem, "label_semantic_style_batch_with_llm", fake_batch)
    monkeypatch.setattr(sem, "is_human_semantic_style_pair", lambda **kwargs: True)
    monkeypatch.setattr(sem, "persist_semantic_style_examples", persisted.extend)

    def fake_mark(*, bot_id, group_id, processed_at, processed_message_id=0):
        marked.append((bot_id, group_id, processed_at, processed_message_id))

    monkeypatch.setattr(sem, "mark_semantic_style_group_processed", fake_mark)

    await mod._produce_semantic_profile({"bot_id": 1, "group_id": 7})

    # 部分失败（第 2 对失败）也落盘成功子集，并把游标推进过全部已尝试对；
    # 全部失败才保留游标待下轮，避免个别失败对卡住整窗反复重发。
    assert [item.example_id for item in persisted] == ["7:101:1", "7:103:1"]
    assert marked == [(1, 7, 1200, 103)]


@pytest.mark.asyncio
async def test_produce_semantic_profile_all_failed_keeps_cursor(monkeypatch) -> None:
    from pallas.product.llm import group_insight_processor as mod
    from pallas.product.llm import repeater_semantic_style as sem

    pairs = [("前句1", "接话1", "adjacent", 11, 12, 101, 1000, False)]
    persisted: list[sem.SemanticStyleExample] = []
    marked: list[tuple[int, int, int, int]] = []

    async def fake_rebuild(**kwargs):
        return pairs

    async def fake_known_bots(group_id):
        return set()

    monkeypatch.setattr(mod, "_known_bots_in_group", fake_known_bots)
    monkeypatch.setattr(mod, "_rebuild_pairs_from_messages", fake_rebuild)
    monkeypatch.setattr(sem, "semantic_style_collection_enabled", lambda *, bot_id, group_id: True)
    monkeypatch.setattr(sem, "semantic_label_budget_ok", lambda: True)
    monkeypatch.setattr(sem, "get_semantic_style_group_cursor", lambda *, bot_id, group_id: (0, 0))
    monkeypatch.setattr(sem, "labeled_semantic_style_reply_ids", lambda bot_id, group_id: set())

    async def fake_batch(items):
        return [None]

    monkeypatch.setattr(sem, "label_semantic_style_batch_with_llm", fake_batch)
    monkeypatch.setattr(sem, "persist_semantic_style_examples", persisted.extend)

    def fake_mark(*, bot_id, group_id, processed_at, processed_message_id=0):
        marked.append((bot_id, group_id, processed_at, processed_message_id))

    monkeypatch.setattr(sem, "mark_semantic_style_group_processed", fake_mark)

    await mod._produce_semantic_profile({"bot_id": 1, "group_id": 7})

    assert persisted == []
    assert marked == []


def test_sweep_wake_delay_aligns_to_next_slot_boundary(monkeypatch) -> None:
    from pallas.product.llm import group_insight_processor as mod

    interval = mod._SWEEP_INTERVAL_SEC
    slot = 1787875200  # a UTC slot boundary (multiple of 21600)
    assert slot % interval == 0

    # 1h before the next slot boundary -> wake there. Since a UTC-day boundary is
    # also a slot boundary (86400 % 21600 == 0), this covers the budget flip too.
    now = slot + interval - 3600
    assert mod._sweep_wake_delay(now) == 3600

    # Exactly on a slot boundary -> full cadence to the next one.
    assert mod._sweep_wake_delay(slot) == interval
