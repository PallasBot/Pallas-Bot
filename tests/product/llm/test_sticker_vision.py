import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.sticker_vision import build_sticker_vision_stats, parse_sticker_vision_choice


def test_prepare_sticker_vision_candidates_downscales_images() -> None:
    from io import BytesIO

    from PIL import Image

    from pallas.product.llm.sticker_vision import prepare_sticker_vision_candidates

    source = BytesIO()
    Image.new("RGB", (1024, 512), "white").save(source, format="PNG")

    prepared = prepare_sticker_vision_candidates([("[CQ:image,file=demo]", source.getvalue())])

    assert prepared[0][0] == "[CQ:image,file=demo]"
    with Image.open(BytesIO(prepared[0][1])) as image:
        assert image.size == (384, 192)


def test_parse_sticker_vision_choice_accepts_json_index() -> None:
    assert parse_sticker_vision_choice('{"index":2}', candidate_count=4) == 1


def test_parse_sticker_vision_choice_rejects_out_of_range_or_explanation() -> None:
    assert parse_sticker_vision_choice('{"index":5}', candidate_count=4) is None
    assert parse_sticker_vision_choice('{"index":true}', candidate_count=4) is None
    assert parse_sticker_vision_choice("我选第 2 张", candidate_count=4) is None


def test_sticker_vision_default_timeout_is_fifteen_seconds() -> None:
    assert LlmConfig().llm_sticker_vision_timeout_sec == 15.0


def test_build_sticker_vision_stats_exposes_result_delivery_and_recent_error() -> None:
    stats = build_sticker_vision_stats(
        [
            {
                "job_id": "job-ok",
                "created_at": 100.0,
                "payload": {
                    "vision_observation": {
                        "state": "selected",
                        "candidate_count": 4,
                        "provider": "yunwu",
                        "model": "gemini-2.5-flash-image",
                        "duration_ms": 840,
                    },
                    "delivery": {"state": "sent"},
                },
            },
            {
                "job_id": "job-fail",
                "created_at": 200.0,
                "payload": {
                    "vision_observation": {
                        "state": "failed",
                        "candidate_count": 3,
                        "provider": "yunwu",
                        "model": "gemini-2.5-flash-image",
                        "duration_ms": 1200,
                        "error": "TimeoutError: request timed out",
                    },
                    "delivery": {"state": "pending"},
                },
            },
        ],
        recent_limit=2,
    )

    assert stats["requests"] == 2
    assert stats["selected"] == 1
    assert stats["failed"] == 1
    assert stats["sent"] == 1
    assert stats["candidate_total"] == 7
    assert stats["avg_duration_ms"] == 1020
    assert stats["recent_error"] == "TimeoutError: request timed out"
    assert stats["recent"][0]["job_id"] == "job-fail"


@pytest.mark.asyncio
async def test_choose_sticker_with_vision_skips_when_fewer_than_three_candidates() -> None:
    from pallas.product.llm import sticker_vision

    observation: dict[str, object] = {}
    selected = await sticker_vision.choose_sticker_with_vision(
        [("[CQ:image,file=a.jpg]", b"a")], user_text="笑死", observation=observation
    )

    assert selected is None
    assert observation["state"] == "skipped"
    assert "候选表情不足 3 张" in str(observation["error"])


@pytest.mark.asyncio
async def test_choose_sticker_with_vision_skips_without_vision_endpoint(monkeypatch) -> None:
    from pallas.product.llm import sticker_vision

    monkeypatch.setattr("pallas.product.llm.providers_store.resolve_endpoint_for_task", lambda *_args, **_kwargs: None)

    observation: dict[str, object] = {}
    candidates = [(f"[CQ:image,file={index}.jpg]", bytes([index])) for index in range(3)]
    selected = await sticker_vision.choose_sticker_with_vision(candidates, user_text="笑死", observation=observation)

    assert selected is None
    assert observation["state"] == "skipped"
    assert "未配置支持图片的表情视觉模型" in str(observation["error"])


@pytest.mark.asyncio
async def test_choose_sticker_with_vision_falls_back_to_none_on_provider_timeout(monkeypatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from pallas.product.llm import sticker_vision

    endpoint = SimpleNamespace(
        model="gemini-2.5-flash-image",
        provider_id="yunwu",
        base_url="https://example.test",
        api_key="k",
        request_method="POST",
        capabilities=["image"],
    )
    monkeypatch.setattr(
        "pallas.product.llm.providers_store.resolve_endpoint_for_task", lambda *_args, **_kwargs: endpoint
    )

    async def slow_complete(*_args, **_kwargs):
        raise TimeoutError("slow")

    monkeypatch.setattr("pallas.product.llm.provider_client.complete_chat_message", slow_complete)
    metric = AsyncMock()
    monkeypatch.setattr("pallas.product.llm.task_metrics.record_bot_llm_task", metric)

    observation: dict[str, object] = {}
    candidates = [(f"[CQ:image,file={index}.jpg]", bytes([index])) for index in range(3)]
    selected = await sticker_vision.choose_sticker_with_vision(
        candidates, user_text="笑死", timeout_sec=0.1, observation=observation
    )

    assert selected is None
    assert observation["state"] == "failed"
    assert "TimeoutError" in str(observation["error"])
    metric.assert_any_call("sticker_vision", "submit_ok")
    metric.assert_any_call("sticker_vision", "callback_fail")


@pytest.mark.asyncio
async def test_choose_sticker_with_vision_falls_back_to_none_on_provider_error(monkeypatch) -> None:
    from types import SimpleNamespace

    from pallas.product.llm import sticker_vision
    from pallas.product.llm.provider_client import LlmProviderError

    endpoint = SimpleNamespace(
        model="gemini-2.5-flash-image",
        provider_id="yunwu",
        base_url="https://example.test",
        api_key="k",
        request_method="POST",
        capabilities=["image"],
    )
    monkeypatch.setattr(
        "pallas.product.llm.providers_store.resolve_endpoint_for_task", lambda *_args, **_kwargs: endpoint
    )

    async def failing_complete(*_args, **_kwargs):
        raise LlmProviderError("HTTP 500")

    monkeypatch.setattr("pallas.product.llm.provider_client.complete_chat_message", failing_complete)

    observation: dict[str, object] = {}
    candidates = [(f"[CQ:image,file={index}.jpg]", bytes([index])) for index in range(3)]
    selected = await sticker_vision.choose_sticker_with_vision(
        candidates, user_text="笑死", timeout_sec=0.1, observation=observation
    )

    assert selected is None
    assert observation["state"] == "failed"


@pytest.mark.asyncio
async def test_choose_sticker_with_vision_reports_no_match_on_invalid_json(monkeypatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from pallas.product.llm import sticker_vision

    endpoint = SimpleNamespace(
        model="gemini-2.5-flash-image",
        provider_id="yunwu",
        base_url="https://example.test",
        api_key="k",
        request_method="POST",
        capabilities=["image"],
    )
    monkeypatch.setattr(
        "pallas.product.llm.providers_store.resolve_endpoint_for_task", lambda *_args, **_kwargs: endpoint
    )

    async def invalid_complete(*_args, **_kwargs):
        return {"content": "我选第二张"}

    monkeypatch.setattr("pallas.product.llm.provider_client.complete_chat_message", invalid_complete)
    metric = AsyncMock()
    monkeypatch.setattr("pallas.product.llm.task_metrics.record_bot_llm_task", metric)

    observation: dict[str, object] = {}
    candidates = [(f"[CQ:image,file={index}.jpg]", bytes([index])) for index in range(3)]
    selected = await sticker_vision.choose_sticker_with_vision(
        candidates, user_text="笑死", timeout_sec=0.1, observation=observation
    )

    assert selected is None
    assert observation["state"] == "no_match"
    metric.assert_any_call("sticker_vision", "callback_ok")


@pytest.mark.asyncio
async def test_enqueue_sticker_vision_job_records_durable_delivery_target(monkeypatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from pallas.product.llm import sticker_vision

    store = SimpleNamespace(enqueue=AsyncMock(side_effect=lambda job: job))
    monkeypatch.setattr(sticker_vision, "build_work_job_store", lambda: store)

    await sticker_vision.enqueue_sticker_vision_job(
        [("[CQ:image,file=a.jpg]", b"a")],
        user_text="笑死",
        timeout_sec=8,
        idempotency_key="sticker:test",
        bot_id=100,
        group_id=200,
        fallback_cq_code="[CQ:image,file=a.jpg]",
    )

    job = next(call.args[0] for call in store.enqueue.await_args_list if call.args[0].kind == "sticker_vision.select")
    assert job.payload["delivery"] == {
        "state": "pending",
        "bot_id": 100,
        "group_id": 200,
        "fallback_cq_code": "[CQ:image,file=a.jpg]",
        "cooldown_sec": 90,
    }


@pytest.mark.asyncio
async def test_enqueue_sticker_vision_labels_only_explicit_candidates(monkeypatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from pallas.product.llm import sticker_vision

    label_candidate = AsyncMock(return_value=True)
    monkeypatch.setattr("pallas.product.llm.sticker_label_jobs.enqueue_sticker_label_candidate", label_candidate)
    store = SimpleNamespace(enqueue=AsyncMock(side_effect=lambda job: job))
    monkeypatch.setattr(sticker_vision, "build_work_job_store", lambda: store)

    await sticker_vision.enqueue_sticker_vision_job(
        [("[CQ:image,file=one.image]", b"one")],
        user_text="test",
        timeout_sec=8,
        idempotency_key="sticker_vision.test:100:200:300",
        bot_id=100,
        group_id=200,
        fallback_cq_code="[CQ:image,file=one.image]",
    )

    label_candidate.assert_awaited_once_with(
        cache_key="[CQ:image,file=one.image]",
        content=b"one",
        source="test_candidate",
    )


@pytest.mark.asyncio
async def test_vision_dispatch_rechecks_guard_and_does_not_send_when_it_is_closed(monkeypatch) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from pallas.product.llm import sticker_vision

    bot = MagicMock()
    bot.call_api = AsyncMock()
    payload = {
        "job_id": "job-guarded",
        "vision_result": {"selected_cq_code": "[CQ:image,file=new-key]"},
        "delivery": {"bot_id": 100, "group_id": 200, "cooldown_sec": 90},
    }
    monkeypatch.setattr(sticker_vision, "claim_sticker_vision_delivery", AsyncMock(return_value=payload))
    monkeypatch.setattr("nonebot.get_bots", lambda: {"100": bot})
    monkeypatch.setattr("pallas.core.shared.utils.media_cache.get_image", AsyncMock(return_value=b"same-content"))
    monkeypatch.setattr(
        "pallas.product.llm.sticker_followup.should_send_repeater_image", lambda *_args, **_kwargs: False
    )
    save = AsyncMock()
    monkeypatch.setattr(sticker_vision, "save_sticker_vision_delivery", save)

    assert await sticker_vision.dispatch_sticker_vision_delivery_once()
    bot.call_api.assert_not_awaited()
    save.assert_awaited_once_with("job-guarded", payload, state="failed", error="表情图发送条件已失效")


@pytest.mark.asyncio
async def test_vision_dispatch_falls_back_to_original_candidate_when_selection_missing(monkeypatch) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from pallas.product.llm import sticker_vision

    bot = MagicMock()
    bot.call_api = AsyncMock()
    fallback = "[CQ:image,file=fallback.jpg]"
    payload = {
        "job_id": "job-fallback",
        "vision_result": {"selected_cq_code": None},
        "delivery": {"bot_id": 100, "group_id": 200, "cooldown_sec": 90, "fallback_cq_code": fallback},
    }
    monkeypatch.setattr(sticker_vision, "claim_sticker_vision_delivery", AsyncMock(return_value=payload))
    monkeypatch.setattr("nonebot.get_bots", lambda: {"100": bot})
    monkeypatch.setattr("pallas.core.shared.utils.media_cache.get_image", AsyncMock(return_value=b"same-content"))
    monkeypatch.setattr(
        "pallas.product.llm.sticker_followup.should_send_repeater_image", lambda *_args, **_kwargs: True
    )
    save = AsyncMock()
    monkeypatch.setattr(sticker_vision, "save_sticker_vision_delivery", save)

    assert await sticker_vision.dispatch_sticker_vision_delivery_once()
    sent = bot.call_api.await_args
    assert sent is not None
    assert sent.kwargs["group_id"] == 200
    assert "image" in str(sent.kwargs["message"])
    save.assert_awaited_once_with("job-fallback", payload, state="sent")


@pytest.mark.asyncio
async def test_save_sticker_vision_delivery_terminal_deletes_pg_row(monkeypatch) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy import Delete, Update

    from pallas.product.llm import sticker_vision

    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    import pallas.core.foundation.db.repository_pg as repo_pg

    monkeypatch.setattr(repo_pg, "get_session", lambda **kw: cm)
    monkeypatch.setattr("pallas.core.foundation.db.runtime.is_postgresql_backend", lambda: True)

    await sticker_vision.save_sticker_vision_delivery(
        "job-x", {"job_id": "job-x", "delivery": {"bot_id": 1}}, state="sent"
    )

    statements = [call.args[0] for call in session.execute.call_args_list]
    assert any(isinstance(s, Delete) for s in statements)
    assert any(isinstance(s, Update) for s in statements)


@pytest.mark.asyncio
async def test_save_sticker_vision_delivery_non_terminal_updates_pg_row(monkeypatch) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy import Delete, Update

    from pallas.product.llm import sticker_vision

    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    import pallas.core.foundation.db.repository_pg as repo_pg

    monkeypatch.setattr(repo_pg, "get_session", lambda **kw: cm)
    monkeypatch.setattr("pallas.core.foundation.db.runtime.is_postgresql_backend", lambda: True)

    await sticker_vision.save_sticker_vision_delivery(
        "job-x", {"job_id": "job-x", "delivery": {"bot_id": 1}}, state="sending"
    )

    statements = [call.args[0] for call in session.execute.call_args_list]
    assert any(isinstance(s, Update) for s in statements)
    assert not any(isinstance(s, Delete) for s in statements)


@pytest.mark.asyncio
async def test_save_sticker_vision_delivery_terminal_deletes_mongo_row(monkeypatch) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from pallas.product.llm import sticker_vision

    collection = MagicMock()
    collection.update_one = AsyncMock()
    collection.delete_one = AsyncMock()
    from pallas.core.foundation.db import modules as db_modules

    monkeypatch.setattr(db_modules.BackgroundJob, "get_pymongo_collection", lambda: collection)
    monkeypatch.setattr("pallas.core.foundation.db.runtime.is_postgresql_backend", lambda: False)

    await sticker_vision.save_sticker_vision_delivery(
        "job-x", {"job_id": "job-x", "delivery": {"bot_id": 1}}, state="failed"
    )

    await_call = collection.update_one.await_args
    assert await_call.args[0] == {"job_id": "job-x"}
    assert await_call.args[1]["$set"]["payload"]["delivery"]["state"] == "failed"
    collection.delete_one.assert_awaited_once_with({"job_id": "job-x"})


@pytest.mark.asyncio
async def test_wait_for_dispatch_wake_returns_true_when_event_set(monkeypatch) -> None:
    from pallas.product.llm import sticker_vision

    monkeypatch.setattr(sticker_vision, "_DISPATCH_FALLBACK_SEC", 0.05)
    sticker_vision.DELIVERY_WAKE_EVENT.set()
    try:
        assert await sticker_vision._wait_for_dispatch_wake() is True
    finally:
        sticker_vision.DELIVERY_WAKE_EVENT.clear()


@pytest.mark.asyncio
async def test_wait_for_dispatch_wake_returns_false_on_timeout(monkeypatch) -> None:
    from pallas.product.llm import sticker_vision

    monkeypatch.setattr(sticker_vision, "_DISPATCH_FALLBACK_SEC", 0.01)
    sticker_vision.DELIVERY_WAKE_EVENT.clear()
    assert await sticker_vision._wait_for_dispatch_wake() is False


@pytest.mark.asyncio
async def test_set_delivery_wake_event_sets_event() -> None:
    from pallas.product.llm import sticker_vision

    try:
        sticker_vision.DELIVERY_WAKE_EVENT.clear()
        await sticker_vision._set_delivery_wake_event()
        assert sticker_vision.DELIVERY_WAKE_EVENT.is_set()
    finally:
        sticker_vision.DELIVERY_WAKE_EVENT.clear()
