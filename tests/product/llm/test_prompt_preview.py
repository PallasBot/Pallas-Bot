from __future__ import annotations

from types import SimpleNamespace

import pytest

from pallas.product.llm import prompt_preview
from pallas.product.llm.assembler.context import ChatContextBundle


@pytest.mark.asyncio
async def test_build_prompt_preview_returns_ordered_sections_and_prompt(monkeypatch) -> None:
    bundle = SimpleNamespace(
        sections=SimpleNamespace(base="BASE", self_identity="IDENTITY"),
        metadata=SimpleNamespace(persona={}),
    )

    async def fake_persona(*args, **kwargs):
        assert args[:3] == (10001, 20002, "今天怎么样")
        return bundle, None, None

    async def fake_context(**kwargs):
        assert kwargs == {
            "bot_id": 10001,
            "group_id": 20002,
            "user_id": 30003,
            "query_text": "今天怎么样",
            "cfg": prompt_preview.get_llm_config(),
            "allow_persistent_memory": True,
            "group_timeline": "",
        }
        return ChatContextBundle(memory="MEMORY", knowledge="", relationship="", person_facts="", mid_term="")

    monkeypatch.setattr(prompt_preview, "build_persona_llm_context", fake_persona)
    monkeypatch.setattr(prompt_preview, "assemble_direct_chat_context", fake_context)

    result = await prompt_preview.build_prompt_preview(
        bot_id=10001,
        group_id=20002,
        user_id=30003,
        query_text="今天怎么样",
    )

    assert result["preview_mode"] is True
    assert result["decision_source"] == "preview_default"
    assert [section["id"] for section in result["sections"]] == [
        "injection_guard",
        "persona",
        "identity",
        "reply_shape",
        "turn_policy",
        "group_timeline",
        "memory",
        "knowledge",
        "relationship",
        "person_facts",
        "mid_term",
        "group_expression",
        "behavior_reference",
        "tool_context",
    ]
    assert result["system_prompt"] == "\n\n".join(
        section["content"] for section in result["sections"] if section["active"]
    )


@pytest.mark.asyncio
async def test_prompt_preview_marks_empty_context_sections_inactive(monkeypatch) -> None:
    bundle = SimpleNamespace(
        sections=SimpleNamespace(base="BASE", self_identity="IDENTITY"),
        metadata=SimpleNamespace(persona={}),
    )
    monkeypatch.setattr(prompt_preview, "build_persona_llm_context", _fake_persona(bundle))
    monkeypatch.setattr(
        prompt_preview,
        "assemble_direct_chat_context",
        _fake_context(ChatContextBundle()),
    )

    result = await prompt_preview.build_prompt_preview(
        bot_id=10001,
        group_id=None,
        user_id=30003,
        query_text="你好",
    )

    memory = next(section for section in result["sections"] if section["id"] == "memory")
    assert memory["active"] is False
    assert memory["content"] == ""


@pytest.mark.asyncio
async def test_prompt_preview_includes_resolved_semantic_style(monkeypatch) -> None:
    bundle = SimpleNamespace(
        sections=SimpleNamespace(base="BASE", self_identity="IDENTITY"),
        metadata=SimpleNamespace(persona={}),
    )
    monkeypatch.setattr(prompt_preview, "build_persona_llm_context", _fake_persona(bundle))
    monkeypatch.setattr(
        prompt_preview,
        "assemble_direct_chat_context",
        _fake_context(ChatContextBundle()),
    )
    resolve_calls = []

    def fake_resolve(
        bot_id,
        group_id,
        scene,
        *,
        request_id,
        query_text,
        recent_assistant_replies,
        bypass_injection_gate,
    ):
        resolve_calls.append((bot_id, group_id, scene, request_id, query_text, list(recent_assistant_replies)))
        assert bypass_injection_gate is True
        return SimpleNamespace(
            matched_examples=[("最近忙什么", "最近在整理东西")],
            baseline_note="短句优先，接话自然。",
            behavior_strategies=[SimpleNamespace(scene="群友求助", action="先给结论", outcome="再补说明")],
        )

    monkeypatch.setattr(prompt_preview, "resolve_cached_semantic_style", fake_resolve)

    result = await prompt_preview.build_prompt_preview(
        bot_id=10001,
        group_id=20002,
        user_id=30003,
        query_text="最近忙什么",
    )

    assert resolve_calls == [(10001, 20002, "group_chat", "preview:10001:20002:30003", "最近忙什么", [])]
    expression = next(section for section in result["sections"] if section["id"] == "group_expression")
    behavior = next(section for section in result["sections"] if section["id"] == "behavior_reference")
    assert "最近在整理东西" in expression["content"]
    assert "短句优先" in expression["content"]
    assert "先给结论" in behavior["content"]
    assert result["traces"]["semantic_style"]["bypassed_injection_gate"] is True


def _fake_persona(bundle):
    async def load(*args, **kwargs):
        return bundle, None, None

    return load


def _fake_context(context):
    async def load(**kwargs):
        return context

    return load
