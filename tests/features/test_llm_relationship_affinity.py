from __future__ import annotations

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.memory.relationship import clamp_affinity
from pallas.product.llm.memory.relationship_auto import extract_relationship_affinity_delta
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
