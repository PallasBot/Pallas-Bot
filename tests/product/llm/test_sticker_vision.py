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
