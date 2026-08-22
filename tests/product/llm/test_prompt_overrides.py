from __future__ import annotations

from types import SimpleNamespace

import pytest

from pallas.product.llm.assembler.chat_prompt import ChatPromptAssembler
from pallas.product.llm.assembler.context import ChatContextBundle
from pallas.product.llm.reply_shape import ReplyShapePolicy
from pallas.product.llm.turn_policy import TurnPolicy


def _inputs() -> dict[str, object]:
    return {
        "core_persona": "原始人格",
        "self_identity": "原始身份",
        "turn_policy": TurnPolicy(
            reply_target="answer",
            seriousness="serious",
            social_action="none",
            allow_teasing=False,
            allow_affection=False,
            needs_tool=False,
            needs_grounding=True,
        ),
        "context": ChatContextBundle(),
        "group_expression": None,
        "reply_shape": ReplyShapePolicy(
            preferred_bubbles=1,
            max_bubbles=1,
            target_chars_min=1,
            target_chars_max=20,
            total_length_band="short",
            rhythm="single",
            max_output_tokens=128,
        ),
    }


def test_assembler_applies_replace_append_and_disable_overrides() -> None:
    prompt = ChatPromptAssembler().assemble(
        **_inputs(),
        section_overrides={
            "persona": {"mode": "replace", "content": "覆盖人格"},
            "identity": {"mode": "append", "content": "补充身份"},
            "turn_policy": {"mode": "disable", "content": ""},
        },
    )

    assert "覆盖人格" in prompt
    assert "原始人格" not in prompt
    assert "原始身份" in prompt
    assert "补充身份" in prompt
    assert "【本轮策略】" not in prompt


def test_prompt_override_store_round_trips_bot_group_scope(tmp_path, monkeypatch) -> None:
    from pallas.product.llm.assembler import prompt_overrides

    monkeypatch.setattr(prompt_overrides, "prompt_overrides_path", lambda: tmp_path / "overrides.json")
    saved = {
        "persona": {"mode": "replace", "content": "群专属人格"},
        "memory": {"mode": "disable", "content": ""},
    }

    prompt_overrides.save_prompt_overrides(bot_id=10001, group_id=20002, sections=saved)

    assert prompt_overrides.load_prompt_overrides(bot_id=10001, group_id=20002) == saved
    assert prompt_overrides.load_prompt_overrides(bot_id=10001, group_id=30003) == {}


def test_prompt_override_store_merges_partial_section_updates(tmp_path, monkeypatch) -> None:
    from pallas.product.llm.assembler import prompt_overrides

    monkeypatch.setattr(prompt_overrides, "prompt_overrides_path", lambda: tmp_path / "overrides.json")
    prompt_overrides.save_prompt_overrides(
        bot_id=10001,
        group_id=20002,
        sections={"persona": {"mode": "replace", "content": "人格"}},
    )
    prompt_overrides.save_prompt_overrides(
        bot_id=10001,
        group_id=20002,
        sections={"identity": {"mode": "append", "content": "身份补充"}},
    )

    assert prompt_overrides.load_prompt_overrides(bot_id=10001, group_id=20002) == {
        "persona": {"mode": "replace", "content": "人格"},
        "identity": {"mode": "append", "content": "身份补充"},
    }


@pytest.mark.asyncio
async def test_prompt_preview_applies_persisted_overrides(monkeypatch) -> None:
    from pallas.product.llm import prompt_preview

    monkeypatch.setattr(
        prompt_preview,
        "load_prompt_overrides",
        lambda bot_id, group_id: {"persona": {"mode": "replace", "content": "预览人格"}},
    )

    async def fake_build_persona_llm_context(*args):
        return _fake_persona_bundle(), None, None

    monkeypatch.setattr(prompt_preview, "build_persona_llm_context", fake_build_persona_llm_context)

    async def fake_assemble_direct_chat_context(**kwargs):
        return ChatContextBundle()

    monkeypatch.setattr(prompt_preview, "assemble_direct_chat_context", fake_assemble_direct_chat_context)
    monkeypatch.setattr(prompt_preview, "resolve_cached_semantic_style", lambda *args, **kwargs: None)

    result = await prompt_preview.build_prompt_preview(
        bot_id=10001,
        group_id=20002,
        user_id=30003,
        query_text="你好",
    )

    persona = next(section for section in result["sections"] if section["id"] == "persona")
    assert persona["content"] == "预览人格"
    assert persona["override"] == {"mode": "replace", "content": "预览人格"}
    assert "预览人格" in result["system_prompt"]


def _fake_persona_bundle():
    return SimpleNamespace(
        sections=SimpleNamespace(base="原始人格", self_identity="原始身份"),
        metadata=SimpleNamespace(persona={}),
    )
