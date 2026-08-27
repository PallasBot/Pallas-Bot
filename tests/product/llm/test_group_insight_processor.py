from types import SimpleNamespace

import pytest

from pallas.product.llm.group_insight_processor import (
    GROUP_INSIGHT_KIND,
    _rebuild_pairs_from_messages,
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
