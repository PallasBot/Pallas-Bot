from __future__ import annotations

import pytest

from src.features.llm.models import ChatSubmitResult
from src.features.llm.polish import build_polish_user_text, maybe_submit_repeater_llm_polish


def test_build_polish_user_text_wraps_candidate() -> None:
    text = build_polish_user_text("  你好呀  ", style_suffix="\n【群风格参考】长度适中。")
    assert text.startswith("【候选回复】你好呀")
    assert "轻改写" in text
    assert "群风格参考" in text


def test_build_polish_user_text_rejects_empty() -> None:
    assert build_polish_user_text("") == ""
    assert build_polish_user_text("   ") == ""


@pytest.mark.asyncio
async def test_maybe_submit_repeater_llm_polish_respects_switches(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.features.llm import config as llm_config_mod

    class FakeEvent:
        group_id = 100
        user_id = 200
        self_id = 300

    monkeypatch.setattr(
        "src.features.llm.polish.get_llm_config",
        lambda: llm_config_mod.LlmConfig(llm_polish_enabled=False, llm_chat_enabled=True),
    )
    assert await maybe_submit_repeater_llm_polish(FakeEvent(), candidate_text="你好") is False

    monkeypatch.setattr(
        "src.features.llm.polish.get_llm_config",
        lambda: llm_config_mod.LlmConfig(llm_polish_enabled=True, llm_chat_enabled=False),
    )
    assert await maybe_submit_repeater_llm_polish(FakeEvent(), candidate_text="你好") is False


@pytest.mark.asyncio
async def test_maybe_submit_repeater_llm_polish_queues_task(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.features.llm import config as llm_config_mod

    class FakeEvent:
        group_id = 100
        user_id = 200
        self_id = 300

    monkeypatch.setattr(
        "src.features.llm.polish.get_llm_config",
        lambda: llm_config_mod.LlmConfig(llm_polish_enabled=True, llm_chat_enabled=True),
    )

    async def fake_compile(*args, **kwargs):
        from src.features.persona.compile_persona_prompt import (
            PersonaPromptBundle,
            PersonaPromptMetadata,
            PersonaPromptSections,
        )

        return PersonaPromptBundle(
            system="system",
            metadata=PersonaPromptMetadata(bot_id=300, group_id=100, persona={}, group_style={}),
            sections=PersonaPromptSections(base="system", bot_behavior="", group_style=""),
        )

    monkeypatch.setattr(
        "src.features.llm.polish.compile_persona_prompt_for",
        fake_compile,
    )
    async def fake_style_suffix(bot_id, group_id):
        return ""

    monkeypatch.setattr(
        "src.features.llm.polish.build_polish_style_suffix",
        fake_style_suffix,
    )

    added: list[str] = []

    async def fake_add_task(task_id, payload):
        added.append(task_id)

    async def fake_remove_task(task_id):
        added.remove(task_id)

    monkeypatch.setattr("src.features.llm.polish.TaskManager.add_task", fake_add_task)
    monkeypatch.setattr("src.features.llm.polish.TaskManager.remove_task", fake_remove_task)

    async def fake_submit(*args, **kwargs):
        return ChatSubmitResult(task_id="task-p1", status="processing", ok=True)

    monkeypatch.setattr("src.features.llm.polish.submit_chat_task", fake_submit)

    ok = await maybe_submit_repeater_llm_polish(FakeEvent(), candidate_text="原句")
    assert ok is True
    assert len(added) == 1
