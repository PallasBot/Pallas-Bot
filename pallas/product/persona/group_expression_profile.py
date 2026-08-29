"""Group-owned expression statistics and semantic-example references."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MIN_READY_MESSAGE_COUNT = 30
MIN_READY_ANSWER_COUNT = 5


class MessageLengthDistribution(BaseModel):
    model_config = ConfigDict(extra="ignore")

    average: float = 0.0
    p50: int = 0
    p90: int = 0


class GroupExpressionAggregate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sample_count: int = 0
    window_hours: int = 0
    message_count: int = 0
    answer_count: int = 0
    distinct_answer_keywords: int = 0
    active_hour_count: int = 0
    messages_per_active_hour: float = 0.0
    message_length: MessageLengthDistribution = Field(default_factory=MessageLengthDistribution)
    answer_ratio: float = 0.0
    repetition_rate: float = 0.0
    forced_teach_weight: float = 0.0
    contamination_skipped_messages: int = 0
    contamination_skipped_answers: int = 0


class SemanticExamplesSummary(BaseModel):
    """Stable snapshot metadata; mutable admission and delivery quotas stay in their owner."""

    model_config = ConfigDict(extra="ignore")

    profile_ref: str = ""
    scene: str = ""
    sample_count: int = 0
    direct_example_count: int = 0
    direct_pair_count: int = 0
    rewrite_seed_count: int = 0
    intensity_counts: dict[str, int] = Field(default_factory=dict)
    form_counts: dict[str, int] = Field(default_factory=dict)
    updated_at: datetime | None = None


class GroupReplyShapeHint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    length_pref: Literal["short", "medium", "long", "any"] = "any"
    bubble_count_p50: int = 0
    bubble_count_p90: int = 0
    segment_char_length_p50: int = 0
    segment_char_length_p90: int = 0
    rhythm_distribution: dict[str, float] = Field(default_factory=dict)


class GroupExpressionProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    aggregate: GroupExpressionAggregate = Field(default_factory=GroupExpressionAggregate)
    examples_summary: SemanticExamplesSummary = Field(default_factory=SemanticExamplesSummary)
    reply_shape: GroupReplyShapeHint = Field(default_factory=GroupReplyShapeHint)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def from_style_profile(cls, profile: dict[str, Any] | None) -> GroupExpressionProfile:
        data = profile if isinstance(profile, dict) else {}
        if "aggregate" in data:
            return cls.model_validate(data)
        sample = data.get("sample") if isinstance(data.get("sample"), dict) else {}
        raw = data.get("raw") if isinstance(data.get("raw"), dict) else {}
        derived = data.get("derived") if isinstance(data.get("derived"), dict) else {}
        skipped = sample.get("contamination_skipped")
        skipped = skipped if isinstance(skipped, dict) else {}
        message_count = int(sample.get("message_count") or 0)
        answer_count = int(sample.get("answer_count") or 0)
        updated_at = data.get("updated_at") or datetime.now(UTC)
        if isinstance(updated_at, (int, float)):
            updated_at = datetime.fromtimestamp(updated_at, tz=UTC)
        legacy_length_pref = str(derived.get("length_pref") or "any").strip()
        if legacy_length_pref not in {"short", "medium", "long", "any"}:
            legacy_length_pref = "any"
        return cls(
            aggregate=GroupExpressionAggregate(
                sample_count=message_count + answer_count,
                window_hours=int(sample.get("window_hours") or 0),
                message_count=message_count,
                answer_count=answer_count,
                distinct_answer_keywords=int(sample.get("distinct_answer_keywords") or 0),
                messages_per_active_hour=float(raw.get("msgs_per_hour_active") or 0.0),
                message_length=MessageLengthDistribution(
                    average=float(raw.get("avg_plain_len") or 0.0),
                    p50=int(raw.get("p50_plain_len") or 0),
                    p90=int(raw.get("p90_plain_len") or 0),
                ),
                answer_ratio=float(raw.get("local_answer_ratio") or 0.0),
                repetition_rate=float(raw.get("repeat_chain_rate") or 0.0),
                forced_teach_weight=float(sample.get("forced_teach_weight") or 0.0),
                contamination_skipped_messages=int(skipped.get("message_count") or 0),
                contamination_skipped_answers=int(skipped.get("answer_count") or 0),
            ),
            reply_shape=GroupReplyShapeHint(length_pref=legacy_length_pref),
            updated_at=updated_at,
        )

    def with_semantic_profile(self, semantic_profile: dict[str, Any] | BaseModel) -> GroupExpressionProfile:
        data = (
            semantic_profile.model_dump(mode="python")
            if isinstance(semantic_profile, BaseModel)
            else dict(semantic_profile)
        )
        semantic_updated_at = data.get("updated_at")
        if isinstance(semantic_updated_at, (int, float)):
            semantic_updated_at = datetime.fromtimestamp(semantic_updated_at, tz=UTC)
        elif not isinstance(semantic_updated_at, datetime):
            semantic_updated_at = None
        summary = SemanticExamplesSummary(
            profile_ref=f"{int(data.get('bot_id') or 0)}:{int(data.get('group_id') or 0)}:{data.get('scene') or ''}",
            scene=str(data.get("scene") or ""),
            sample_count=int(data.get("sample_count") or 0),
            direct_example_count=len(data.get("direct_examples") or []),
            direct_pair_count=len(data.get("direct_pairs") or []),
            rewrite_seed_count=len(data.get("rewrite_seeds") or []),
            intensity_counts={str(key): int(value) for key, value in dict(data.get("intensity_counts") or {}).items()},
            form_counts={str(key): int(value) for key, value in dict(data.get("form_counts") or {}).items()},
            updated_at=semantic_updated_at,
        )
        # reply_shape 只由群消息（group_profiler）计算，不再被语义 profile 覆写；
        # 语义层仅贡献 examples_summary 这类信息展示字段。
        updated_at = max(self.updated_at, semantic_updated_at) if semantic_updated_at else self.updated_at
        return self.model_copy(update={"examples_summary": summary, "updated_at": updated_at})


def group_expression_profile_ready(profile: GroupExpressionProfile) -> bool:
    return (
        profile.aggregate.message_count >= MIN_READY_MESSAGE_COUNT
        and profile.aggregate.answer_count >= MIN_READY_ANSWER_COUNT
    )


def resolve_group_expression_profile(
    style_profile: dict[str, Any] | None,
    semantic_profile: dict[str, Any] | BaseModel | None = None,
) -> GroupExpressionProfile:
    profile = GroupExpressionProfile.from_style_profile(style_profile)
    return profile.with_semantic_profile(semantic_profile) if semantic_profile is not None else profile
