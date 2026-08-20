from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.memory.affinity_scorer import score_affinity_with_llm
from pallas.product.llm.memory.relationship import clamp_affinity
from pallas.product.llm.memory.relationship_auto import extract_relationship_affinity_delta
from pallas.product.llm.memory.relationship_persist import maybe_persist_relationship_from_utterance
from pallas.product.llm.memory.relationship_store import RelationshipProfile


def test_affinity_config_defaults() -> None:
    cfg = LlmConfig()
    assert cfg.llm_relationship_affinity_enabled is True
    assert cfg.llm_relationship_affinity_delta_max == 0.15
    assert cfg.llm_relationship_affinity_llm_cooldown_s == 60
    assert cfg.llm_relationship_affinity_daily_decay_step == 0.02
    assert cfg.llm_relationship_affinity_silence_threshold == -0.3
    assert cfg.llm_relationship_affinity_silence_max_penalty == 30


def test_clamp_affinity() -> None:
    assert clamp_affinity(1.5) == 1.0
    assert clamp_affinity(-1.5) == -1.0
    assert clamp_affinity(0.3) == 0.3
    assert clamp_affinity(0.12345) == 0.123


def test_extract_relationship_affinity_delta_positive() -> None:
    delta = extract_relationship_affinity_delta("牛牛你好棒，喜欢你！")
    assert delta > 0


def test_extract_relationship_affinity_delta_negative() -> None:
    delta = extract_relationship_affinity_delta("傻牛，滚出去！")
    assert delta < 0


def test_extract_relationship_affinity_delta_negative_wins_over_positive() -> None:
    delta = extract_relationship_affinity_delta("喜欢你，但是你是废物")
    assert delta < 0


def test_extract_relationship_affinity_delta_neutral() -> None:
    assert extract_relationship_affinity_delta("牛牛帮我唱歌") == 0.0
    assert extract_relationship_affinity_delta("今天天气不错") == 0.0


def test_relationship_note_row_has_affinity() -> None:
    from pallas.core.foundation.db.repository_pg import LlmRelationshipNoteRow

    col_names = {column.name for column in LlmRelationshipNoteRow.__table__.columns}
    assert "affinity" in col_names


def test_relationship_note_document_has_affinity() -> None:
    from pallas.core.foundation.db.modules import LlmRelationshipNote

    fields = set(LlmRelationshipNote.model_fields)
    assert "affinity" in fields


def test_relationship_profile_has_affinity() -> None:
    profile = RelationshipProfile(affinity=-0.5)
    assert profile.affinity == -0.5
    assert profile.has_affinity is True
    assert RelationshipProfile().has_affinity is False


@pytest.mark.asyncio
async def test_score_affinity_with_llm_parses_json() -> None:
    payload = json.dumps({"affinity_delta": -0.6, "confidence": 0.9, "reason": "反讽"})
    with patch(
        "pallas.product.llm.memory.affinity_scorer.complete_chat_message",
        new=AsyncMock(return_value={"content": f"```json\n{payload}\n```"}),
    ):
        result = await score_affinity_with_llm("你还不感谢我", task="llm.relationship.affinity")
    assert result["affinity_delta"] == -0.6
    assert result["confidence"] == 0.9


@pytest.mark.asyncio
async def test_score_affinity_with_llm_handles_bad_json() -> None:
    with patch(
        "pallas.product.llm.memory.affinity_scorer.complete_chat_message",
        new=AsyncMock(return_value={"content": "不是 JSON"}),
    ):
        result = await score_affinity_with_llm("随便说", task="llm.relationship.affinity")
    assert result is None


@pytest.mark.asyncio
async def test_score_affinity_with_llm_clamps_bounds() -> None:
    payload = json.dumps({"affinity_delta": 1.5, "confidence": 2.0, "reason": "x"})
    with patch(
        "pallas.product.llm.memory.affinity_scorer.complete_chat_message",
        new=AsyncMock(return_value={"content": payload}),
    ):
        result = await score_affinity_with_llm("太爱你了", task="llm.relationship.affinity")
    assert result["affinity_delta"] == 1.0
    assert result["confidence"] == 1.0


@pytest.mark.asyncio
async def test_score_affinity_with_llm_handles_non_numeric() -> None:
    payload = json.dumps({"affinity_delta": "很讨厌", "confidence": 0.5, "reason": "x"})
    with patch(
        "pallas.product.llm.memory.affinity_scorer.complete_chat_message",
        new=AsyncMock(return_value={"content": payload}),
    ):
        result = await score_affinity_with_llm("随便说", task="llm.relationship.affinity")
    assert result is None


@pytest.mark.asyncio
async def test_score_affinity_with_llm_handles_non_dict() -> None:
    with patch(
        "pallas.product.llm.memory.affinity_scorer.complete_chat_message",
        new=AsyncMock(return_value={"content": "[1, 2, 3]"}),
    ):
        result = await score_affinity_with_llm("随便说", task="llm.relationship.affinity")
    assert result is None


@pytest.mark.asyncio
async def test_score_affinity_with_llm_handles_empty_content() -> None:
    with patch(
        "pallas.product.llm.memory.affinity_scorer.complete_chat_message",
        new=AsyncMock(return_value={"content": ""}),
    ):
        result = await score_affinity_with_llm("随便说", task="llm.relationship.affinity")
    assert result is None


@pytest.mark.asyncio
async def test_score_affinity_with_llm_handles_provider_error() -> None:
    with patch(
        "pallas.product.llm.memory.affinity_scorer.complete_chat_message",
        new=AsyncMock(side_effect=RuntimeError("provider down")),
    ):
        result = await score_affinity_with_llm("随便说", task="llm.relationship.affinity")
    assert result is None


@pytest.mark.asyncio
async def test_score_affinity_with_llm_truncates_long_input() -> None:
    long_text = "我爱你" * 100
    captured: dict = {}

    async def fake_complete(messages, **kwargs):
        captured["prompt"] = messages[0]["content"]
        return {"content": json.dumps({"affinity_delta": 0.3, "confidence": 0.8, "reason": "x"})}

    with patch(
        "pallas.product.llm.memory.affinity_scorer.complete_chat_message",
        new=AsyncMock(side_effect=fake_complete),
    ):
        result = await score_affinity_with_llm(long_text, task="llm.relationship.affinity")
    assert result is not None
    quoted = captured["prompt"].split("群友的话：", 1)[1]
    assert len(quoted) <= 60


@pytest.mark.asyncio
async def test_persist_rules_affinity_no_llm_when_hit() -> None:
    cfg = LlmConfig(llm_chat_enabled=True, llm_relationship_notes_enabled=True)
    upsert = AsyncMock(return_value=True)
    with (
        patch(
            "pallas.product.llm.memory.relationship_persist.upsert_relationship_profile",
            new=upsert,
        ),
        patch(
            "pallas.product.llm.memory.relationship_persist.score_affinity_with_llm",
            new=AsyncMock(return_value={"affinity_delta": -0.6, "confidence": 0.9, "reason": "反讽"}),
        ) as llm,
    ):
        ok = await maybe_persist_relationship_from_utterance(1, 2, 3, "傻牛滚出去", speak_trigger="to_me", cfg=cfg)
    assert ok is True
    assert llm.await_count == 0
    kwargs = upsert.await_args.kwargs
    assert kwargs["affinity_delta_add"] == -0.08


@pytest.mark.asyncio
async def test_persist_llm_affinity_when_rule_miss() -> None:
    cfg = LlmConfig(llm_chat_enabled=True, llm_relationship_notes_enabled=True)
    upsert = AsyncMock(return_value=True)
    with (
        patch(
            "pallas.product.llm.memory.relationship_persist.upsert_relationship_profile",
            new=upsert,
        ),
        patch(
            "pallas.product.llm.memory.relationship_persist.score_affinity_with_llm",
            new=AsyncMock(return_value={"affinity_delta": -0.6, "confidence": 0.9, "reason": "反讽"}),
        ) as llm,
    ):
        ok = await maybe_persist_relationship_from_utterance(1, 2, 3, "你还不感谢我", speak_trigger="followup", cfg=cfg)
    assert ok is True
    assert llm.await_count == 1
    kwargs = upsert.await_args.kwargs
    assert kwargs["affinity_delta_add"] == -0.6
