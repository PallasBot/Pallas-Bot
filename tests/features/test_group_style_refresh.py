from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_group_style_dirty_mark_and_pop_batch() -> None:
    from pallas.product.persona.group_style_refresh import (
        clear_group_style_dirty_state,
        mark_group_style_dirty,
        pop_dirty_group_style_batch,
    )

    clear_group_style_dirty_state()
    mark_group_style_dirty(3)
    mark_group_style_dirty(1)
    mark_group_style_dirty(3)

    assert pop_dirty_group_style_batch(1) == [1]
    assert pop_dirty_group_style_batch(8) == [3]
    assert pop_dirty_group_style_batch(8) == []


@pytest.mark.asyncio
async def test_learner_marks_group_style_dirty_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater.learner import Learner

    marked: list[int] = []

    async def fake_group_messages_before(_chat):
        return []

    async def fake_message_insert(_chat, topics_callback):  # noqa: ARG001
        return None

    monkeypatch.setattr("packages.repeater.learner.group_messages_before", fake_group_messages_before)
    monkeypatch.setattr("packages.repeater.learner.MessageStore.message_insert", fake_message_insert)
    monkeypatch.setattr(
        "pallas.product.persona.group_style_refresh.mark_group_style_dirty", lambda gid: marked.append(gid)
    )
    monkeypatch.setattr(
        "packages.repeater.responder.Responder._repeat_ignore_user_ids",
        staticmethod(lambda: set()),
    )

    async def fake_should_skip_repeater_learn(*_args, **_kwargs):
        return False

    monkeypatch.setattr(
        "packages.duel.duel_session.should_skip_repeater_learn",
        fake_should_skip_repeater_learn,
    )

    chat = SimpleNamespace(
        raw_message="你好",
        user_id=123,
        group_id=456,
        plain_text="你好",
        keywords="你好",
        is_plain_text=True,
        time=1_700_000_000,
    )

    got = await Learner.learn(chat, __import__("asyncio").Lock(), {})
    assert got is True
    assert marked == [456]


@pytest.mark.asyncio
async def test_refresh_group_style_profile_writes_profile_and_invalidates_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.persona.group_style_refresh import refresh_group_style_profile

    invalidated: list[int | None] = []
    written: list[tuple[int, dict]] = []

    class DummyGroupRepo:
        async def get(self, key_id: int, ignore_cache=False):  # noqa: ARG002
            return None

        async def upsert_field(self, key_id: int, field: str, value):
            assert field == "style_profile"
            written.append((key_id, value))

    class DummyMessageRepo:
        async def find_recent_in_group(self, group_id: int, *, before_time=None, user_id=None, limit=8):  # noqa: ARG002
            return [SimpleNamespace(group_id=group_id, plain_text="草", time=1_700_000_000 - i * 60) for i in range(30)]

    class DummyContextRepo:
        async def list_answers_for_group_since(self, group_id: int, cutoff_time: int):  # noqa: ARG002
            from pallas.core.foundation.db.modules import Answer

            return [
                Answer(keywords=f"k{i}", group_id=group_id, count=1, time=1_700_000_000 - i * 60, messages=["哈"])
                for i in range(5)
            ]

    monkeypatch.setattr(
        "pallas.product.persona.group_style_refresh.make_group_config_repository", lambda: DummyGroupRepo()
    )
    monkeypatch.setattr(
        "pallas.product.persona.group_style_refresh.make_message_repository", lambda: DummyMessageRepo()
    )
    monkeypatch.setattr(
        "pallas.product.persona.group_style_refresh.make_local_context_repository", lambda: DummyContextRepo()
    )
    monkeypatch.setattr(
        "pallas.product.persona.group_style_refresh.invalidate_persona_cache",
        lambda bot_id=None: invalidated.append(bot_id),
    )

    ok, used_llm = await refresh_group_style_profile(777)
    assert ok is True
    assert used_llm is False
    assert written
    assert written[0][0] == 777
    assert "sample" in written[0][1]
    assert invalidated == [None]


@pytest.mark.asyncio
async def test_refresh_dirty_group_style_batch_isolates_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.persona.group_style_refresh import (
        clear_group_style_dirty_state,
        mark_group_style_dirty,
        refresh_dirty_group_style_batch,
    )

    seen: list[int] = []

    async def fake_refresh(
        group_id: int, *, window_hours: int = 168, allow_llm_refine: bool = True
    ) -> tuple[bool, bool]:  # noqa: ARG001
        seen.append(group_id)
        if group_id == 2:
            raise RuntimeError("boom")
        return True, False

    monkeypatch.setattr("pallas.product.persona.group_style_refresh.refresh_group_style_profile", fake_refresh)
    clear_group_style_dirty_state()
    mark_group_style_dirty(1)
    mark_group_style_dirty(2)
    mark_group_style_dirty(3)

    refreshed = await refresh_dirty_group_style_batch(limit=8)

    assert refreshed == 2
    assert seen == [1, 2, 3]
