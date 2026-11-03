from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from pallas.product.llm.behavior import BehaviorOutcome, BehaviorRun, BehaviorScene, infer_behavior_feedback
from pallas.product.llm.behavior_feedback import settle_pending_behavior_runs
from pallas.product.llm.session_models import LlmChatTurn, LlmHistorySessionSummary


def _run(request_id: str, created_at: int, *, bot_id: int = 1, user_id: int = 2, group_id: int = 3) -> BehaviorRun:
    return BehaviorRun(
        request_id=request_id,
        bot_id=bot_id,
        user_id=user_id,
        group_id=group_id,
        created_at=created_at,
        scene=BehaviorScene.SMALLTALK,
    )


def _turn(role: str, content: str, created_at: int, *, user_id: int = 2) -> SimpleNamespace:
    return SimpleNamespace(role=role, content=content, created_at=created_at, user_id=user_id)


@pytest.mark.parametrize("scope", ["session", "ambient"])
def test_same_second_user_messages_keep_feedback_unresolved(scope: str) -> None:
    run = _run("req-same-second", created_at=100)
    before = _turn("user", "跑题", 100)
    assistant = _turn("assistant", "回复", 100)
    after = _turn("user", "哈哈", 100)
    turns, ambient = ([before, assistant, after], []) if scope == "session" else ([assistant], [before, after])

    assert infer_behavior_feedback(run=run, turns=turns, ambient_turns=ambient, now=300) == (None, {})


@pytest.mark.parametrize("scope", ["session", "ambient"])
def test_same_second_pre_reply_message_alone_keeps_feedback_unresolved(scope: str) -> None:
    run = _run("req-same-second-before", created_at=100)
    before = _turn("user", "跑题", 100)
    assistant = _turn("assistant", "回复", 100)
    turns, ambient = ([before, assistant], []) if scope == "session" else ([assistant], [before])

    assert infer_behavior_feedback(run=run, turns=turns, ambient_turns=ambient, now=300) == (None, {})


@pytest.mark.parametrize("scope", ["session", "ambient"])
def test_same_second_ambiguity_stays_unresolved_despite_later_evidence(scope: str) -> None:
    run = _run("req-same-second-later", created_at=100)
    ambiguous = _turn("user", "跑题", 100)
    assistant = _turn("assistant", "回复", 100)
    later = _turn("user", "哈哈", 101)
    turns, ambient = ([ambiguous, assistant, later], []) if scope == "session" else ([assistant], [ambiguous, later])

    assert infer_behavior_feedback(run=run, turns=turns, ambient_turns=ambient, now=300) == (None, {})


def test_unambiguous_later_evidence_remains_classifiable() -> None:
    run = _run("req-later-only", created_at=100)
    assistant = _turn("assistant", "回复", 100)
    later = _turn("user", "哈哈", 101)

    outcome, payload = infer_behavior_feedback(run=run, turns=[assistant, later], now=300)

    assert outcome == BehaviorOutcome.ENGAGED
    assert payload["matched_signal"] == "engaged_token"
    assert payload["observed_turn_count"] == 1


@pytest.mark.asyncio
async def test_settle_pending_behavior_runs_does_not_persist_same_second_ambiguity(monkeypatch) -> None:
    from pallas.product.llm import behavior_feedback as mod

    monkeypatch.setattr(mod, "is_llm_session_store_available", lambda: True)
    run = _run("req-same-second-pending", created_at=100)
    monkeypatch.setattr(mod, "list_behavior_runs", lambda limit: [run])

    async def fake_user_messages(bot_id, group_id, user_id, limit=50):
        return [
            _turn("user", "跑题", 100),
            _turn("assistant", "回复", 100),
            _turn("user", "哈哈", 100),
            _turn("user", "你别转话题", 101),
        ]

    async def fake_ambient(bot_id, group_id, limit=50):
        return []

    monkeypatch.setattr(mod, "list_user_llm_messages", fake_user_messages)
    monkeypatch.setattr(mod, "list_group_ambient_messages", fake_ambient)
    settle = Mock(side_effect=AssertionError("ambiguous feedback must not be persisted"))
    monkeypatch.setattr(mod, "settle_behavior_run_outcome", settle)

    assert await settle_pending_behavior_runs(now=300) == 0
    settle.assert_not_called()
    assert run.final_outcome is None
    assert run.score_delta == 0


@pytest.mark.asyncio
async def test_history_detail_does_not_persist_same_second_ambiguity(monkeypatch) -> None:
    from pallas.product.llm import session_store as mod

    run = _run("req-same-second-history", created_at=100, bot_id=10, user_id=200, group_id=100)
    monkeypatch.setattr(
        mod,
        "list_user_llm_messages",
        AsyncMock(
            return_value=[
                LlmChatTurn(role="user", content="跑题", user_id=200, created_at=100),
                LlmChatTurn(role="assistant", content="回复", user_id=200, created_at=100),
                LlmChatTurn(role="user", content="哈哈", user_id=200, created_at=100),
            ]
        ),
    )
    monkeypatch.setattr(mod, "list_group_ambient_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        mod,
        "list_llm_history_sessions",
        AsyncMock(
            return_value=[
                LlmHistorySessionSummary(
                    session_key="10:100:200",
                    bot_id=10,
                    group_id=100,
                    user_id=200,
                    turn_count=3,
                    first_created_at=100,
                    last_created_at=100,
                    last_role="user",
                    last_content="哈哈",
                )
            ]
        ),
    )
    monkeypatch.setattr(mod, "list_behavior_runs_for_session", lambda **kwargs: [run])
    settle = Mock(side_effect=AssertionError("ambiguous feedback must not be persisted"))
    monkeypatch.setattr(mod, "settle_behavior_run_outcome", settle)
    monkeypatch.setattr("pallas.product.llm.repeater_feedback.list_feedback_entries_for_session", lambda **kwargs: [])

    detail = await mod.get_llm_history_session_detail(bot_id=10, group_id=100, user_id=200)

    assert detail is not None
    assert detail.behavior_runs[0]["final_outcome"] is None
    settle.assert_not_called()
    assert run.final_outcome is None
    assert run.score_delta == 0


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


@pytest.mark.asyncio
async def test_settle_pending_behavior_runs_caps_per_pass(monkeypatch) -> None:
    """每轮结算条数受上限约束，backlog 分多轮消化。"""
    from pallas.product.llm import behavior_feedback as mod

    monkeypatch.setattr(mod, "is_llm_session_store_available", lambda: True)
    runs = [_run(f"req-{i}", created_at=100) for i in range(10)]
    monkeypatch.setattr(mod, "list_behavior_runs", lambda limit: runs)
    monkeypatch.setattr(mod, "_SETTLE_MAX_PER_PASS", 3)

    async def fake_user_messages(bot_id, group_id, user_id, limit=50):
        return []

    async def fake_ambient(bot_id, group_id, limit=50):
        return []

    monkeypatch.setattr(mod, "list_user_llm_messages", fake_user_messages)
    monkeypatch.setattr(mod, "list_group_ambient_messages", fake_ambient)

    settled: list[str] = []

    def fake_settle(request_id, *, final_outcome, auto_feedback_payload=None):
        settled.append(request_id)
        return _run(request_id, created_at=100)

    monkeypatch.setattr(mod, "settle_behavior_run_outcome", fake_settle)

    count = await settle_pending_behavior_runs(now=300)
    assert count == 3
    assert settled == ["req-0", "req-1", "req-2"]
