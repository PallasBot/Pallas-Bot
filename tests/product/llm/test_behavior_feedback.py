from __future__ import annotations

import pytest

from pallas.product.llm.behavior import BehaviorOutcome, BehaviorRun, BehaviorScene
from pallas.product.llm.behavior_feedback import settle_pending_behavior_runs


def _run(request_id: str, created_at: int, *, bot_id: int = 1, user_id: int = 2, group_id: int = 3) -> BehaviorRun:
    return BehaviorRun(
        request_id=request_id,
        bot_id=bot_id,
        user_id=user_id,
        group_id=group_id,
        created_at=created_at,
        scene=BehaviorScene.SMALLTALK,
    )


@pytest.mark.asyncio
async def test_settle_pending_behavior_runs_settles_expired_window(monkeypatch) -> None:
    from pallas.product.llm import behavior_feedback as mod

    monkeypatch.setattr(mod, "is_llm_session_store_available", lambda: True)
    runs = [_run("req-1", created_at=100)]
    monkeypatch.setattr(mod, "list_behavior_runs", lambda limit: runs)

    async def fake_user_messages(bot_id, group_id, user_id, limit=50):
        return []

    async def fake_ambient(bot_id, group_id, limit=50):
        return []

    monkeypatch.setattr(mod, "list_user_llm_messages", fake_user_messages)
    monkeypatch.setattr(mod, "list_group_ambient_messages", fake_ambient)

    settled: list[tuple[str, object]] = []

    def fake_settle(request_id, *, final_outcome, auto_feedback_payload=None):
        settled.append((request_id, final_outcome))
        return _run(request_id, created_at=100)

    monkeypatch.setattr(mod, "settle_behavior_run_outcome", fake_settle)

    count = await settle_pending_behavior_runs(now=300)
    assert count == 1
    assert settled == [("req-1", BehaviorOutcome.IGNORED)]


@pytest.mark.asyncio
async def test_settle_pending_behavior_runs_skips_within_window(monkeypatch) -> None:
    from pallas.product.llm import behavior_feedback as mod

    monkeypatch.setattr(mod, "is_llm_session_store_available", lambda: True)
    runs = [_run("req-1", created_at=250)]
    monkeypatch.setattr(mod, "list_behavior_runs", lambda limit: runs)

    async def fake_user_messages(bot_id, group_id, user_id, limit=50):
        return []

    async def fake_ambient(bot_id, group_id, limit=50):
        return []

    monkeypatch.setattr(mod, "list_user_llm_messages", fake_user_messages)
    monkeypatch.setattr(mod, "list_group_ambient_messages", fake_ambient)

    def fake_settle(request_id, *, final_outcome, auto_feedback_payload=None):
        raise AssertionError("within-window run must not be settled")

    monkeypatch.setattr(mod, "settle_behavior_run_outcome", fake_settle)

    count = await settle_pending_behavior_runs(now=300)
    assert count == 0


@pytest.mark.asyncio
async def test_settle_pending_behavior_runs_skips_already_settled(monkeypatch) -> None:
    from pallas.product.llm import behavior_feedback as mod

    monkeypatch.setattr(mod, "is_llm_session_store_available", lambda: True)
    run = _run("req-1", created_at=100)
    run.final_outcome = BehaviorOutcome.ENGAGED
    runs = [run]
    monkeypatch.setattr(mod, "list_behavior_runs", lambda limit: runs)

    async def fake_user_messages(bot_id, group_id, user_id, limit=50):
        return []

    async def fake_ambient(bot_id, group_id, limit=50):
        return []

    monkeypatch.setattr(mod, "list_user_llm_messages", fake_user_messages)
    monkeypatch.setattr(mod, "list_group_ambient_messages", fake_ambient)

    def fake_settle(request_id, *, final_outcome, auto_feedback_payload=None):
        raise AssertionError("already-settled run must not be re-settled")

    monkeypatch.setattr(mod, "settle_behavior_run_outcome", fake_settle)

    count = await settle_pending_behavior_runs(now=300)
    assert count == 0


@pytest.mark.asyncio
async def test_settle_pending_behavior_runs_skips_when_store_unavailable(monkeypatch) -> None:
    from pallas.product.llm import behavior_feedback as mod

    monkeypatch.setattr(mod, "is_llm_session_store_available", lambda: False)

    def fake_list(limit):
        raise AssertionError("must not read runs when store unavailable")

    monkeypatch.setattr(mod, "list_behavior_runs", fake_list)

    count = await settle_pending_behavior_runs(now=300)
    assert count == 0
