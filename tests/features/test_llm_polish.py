from __future__ import annotations

import pytest

from pallas.product.llm.models import ChatSubmitResult
from pallas.product.llm.polish import build_polish_user_text, maybe_submit_repeater_llm_polish


def test_build_polish_user_text_wraps_candidate() -> None:
    text = build_polish_user_text("  你好呀  ", style_suffix="\n【群风格参考】长度适中。")
    assert text.startswith("【候选回复】你好呀")
    assert "轻顺口气" in text
    assert "群风格参考" in text


def test_build_polish_user_text_medium_intensity() -> None:
    text = build_polish_user_text("候选一句", intensity="medium")
    assert "近义改写" in text
    assert "另起话题" in text


def test_build_polish_user_text_rejects_empty() -> None:
    assert build_polish_user_text("") == ""
    assert build_polish_user_text("   ") == ""


@pytest.mark.asyncio
async def test_maybe_submit_repeater_llm_polish_force_for_cue(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import config as llm_config_mod

    class FakeEvent:
        group_id = 100
        user_id = 200
        self_id = 300

        def is_tome(self) -> bool:
            return False

    monkeypatch.setattr(
        "pallas.product.llm.polish.get_llm_config",
        lambda: llm_config_mod.LlmConfig(
            llm_polish_enabled=False,
            llm_chat_enabled=True,
            llm_select_enabled=True,
        ),
    )

    async def fake_style_suffix(bot_id, group_id):
        return ""

    monkeypatch.setattr("pallas.product.llm.polish.build_polish_style_suffix", fake_style_suffix)

    class Bundle:
        system_prompt = "system"
        temperature = 0.5
        token_count = 80
        llm_rewrite_metadata = None

    async def fake_persona(*args, **kwargs):
        return Bundle()

    monkeypatch.setattr(
        "pallas.product.llm.polish.build_repeater_llm_persona_context",
        fake_persona,
    )

    async def fake_feedback(**kwargs):
        return ""

    monkeypatch.setattr(
        "pallas.product.llm.feedback_chat_hint.load_repeater_feedback_system_suffix",
        fake_feedback,
    )

    added: list[str] = []

    async def fake_add_task(request_id, payload):
        added.append(request_id)

    async def fake_submit(*args, **kwargs):
        return ChatSubmitResult(ok=True, status="queued")

    monkeypatch.setattr("pallas.product.llm.polish.TaskManager.add_task", fake_add_task)
    monkeypatch.setattr("pallas.product.llm.polish.submit_chat_task", fake_submit)
    monkeypatch.setattr("pallas.product.llm.polish.record_bot_llm_task", lambda *a, **k: None)

    assert (
        await maybe_submit_repeater_llm_polish(
            FakeEvent(),
            candidate_text="草",
            force_for_cue=True,
            intensity="medium",
        )
        is True
    )
    assert added


@pytest.mark.asyncio
async def test_maybe_submit_repeater_llm_polish_respects_switches(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import config as llm_config_mod

    class FakeEvent:
        group_id = 100
        user_id = 200
        self_id = 300

        def is_tome(self) -> bool:
            return False

    monkeypatch.setattr(
        "pallas.product.llm.polish.get_llm_config",
        lambda: llm_config_mod.LlmConfig(llm_polish_enabled=False, llm_chat_enabled=True),
    )
    assert await maybe_submit_repeater_llm_polish(FakeEvent(), candidate_text="你好") is False

    monkeypatch.setattr(
        "pallas.product.llm.polish.get_llm_config",
        lambda: llm_config_mod.LlmConfig(llm_polish_enabled=True, llm_chat_enabled=False),
    )
    assert await maybe_submit_repeater_llm_polish(FakeEvent(), candidate_text="你好") is False


@pytest.mark.asyncio
async def test_maybe_submit_repeater_llm_polish_queues_task(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import config as llm_config_mod

    class FakeEvent:
        group_id = 100
        user_id = 200
        self_id = 300

        def is_tome(self) -> bool:
            return False

    monkeypatch.setattr(
        "pallas.product.llm.polish.get_llm_config",
        lambda: llm_config_mod.LlmConfig(llm_polish_enabled=True, llm_chat_enabled=True),
    )

    class Bundle:
        system_prompt = "system"
        temperature = 0.6
        token_count = 96
        llm_rewrite_metadata = None

    async def fake_persona(*args, **kwargs):
        return Bundle()

    monkeypatch.setattr(
        "pallas.product.llm.polish.build_repeater_llm_persona_context",
        fake_persona,
    )

    async def fake_feedback(**kwargs):
        return ""

    monkeypatch.setattr(
        "pallas.product.llm.feedback_chat_hint.load_repeater_feedback_system_suffix",
        fake_feedback,
    )

    async def fake_style_suffix(bot_id, group_id):
        return ""

    monkeypatch.setattr(
        "pallas.product.llm.polish.build_polish_style_suffix",
        fake_style_suffix,
    )

    added: list[str] = []

    async def fake_add_task(task_id, payload):
        added.append(task_id)

    async def fake_remove_task(task_id):
        added.remove(task_id)

    monkeypatch.setattr("pallas.product.llm.polish.TaskManager.add_task", fake_add_task)
    monkeypatch.setattr("pallas.product.llm.polish.TaskManager.remove_task", fake_remove_task)
    monkeypatch.setattr("pallas.product.llm.polish.record_bot_llm_task", lambda *a, **k: None)

    async def fake_submit(*args, **kwargs):
        return ChatSubmitResult(task_id="task-p1", status="processing", ok=True)

    monkeypatch.setattr("pallas.product.llm.polish.submit_chat_task", fake_submit)

    ok = await maybe_submit_repeater_llm_polish(FakeEvent(), candidate_text="原句")
    assert ok is True
    assert len(added) == 1
