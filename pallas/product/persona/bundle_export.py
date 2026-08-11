"""Persona 资产导出（OPT-LLM-024）：跨站点可复用的 JSON bundle + schema。"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from pallas.product.persona.compile_persona_prompt import (
    PROMPT_PROFILE_CHAT,
    PersonaPromptBundle,
    compile_persona_prompt_for,
)
from pallas.product.persona.group_expression_profile import (
    GroupExpressionProfile,
    group_expression_profile_ready,
)

PERSONA_ASSET_SCHEMA_VERSION = 1


class PersonaPromptSectionsV1(BaseModel):
    base: str
    self_identity: str = ""
    preset_layers: str = ""
    disposition: str = ""
    bot_behavior: str
    group_style: str = ""
    group_expression: str = ""


class LegacyGroupStyleSignalsV1(BaseModel):
    reply_bias_mul: float | None = None
    speak_bias_mul: float | None = None
    length_pref: str = "any"
    chaos_bias: float | None = None
    warmth_bias: float | None = None
    assertiveness_bias: float | None = None
    avg_plain_len: float = 0.0
    p50_plain_len: int = 0
    p90_plain_len: int = 0
    msgs_per_hour_active: float = 0.0
    local_answer_ratio: float = 0.0
    repeat_chain_rate: float = 0.0
    civility_score: float | None = None
    harsh_msg_ratio: float | None = None
    polite_msg_ratio: float | None = None
    punct_aggression_avg: float | None = None


class LegacyGroupStyleSnapshotV1(BaseModel):
    """V1 read-only compatibility view; new writes use group_expression_profile."""

    version: Literal[1] = 1
    ready: bool = Field(description="True when the new aggregate contains at least one observed sample.")
    updated_at: str | None = None
    sample: dict[str, Any] | None = None
    signals: LegacyGroupStyleSignalsV1 | None = None
    hints: list[str] = Field(default_factory=list)


class PersonaPromptMetadataV1(BaseModel):
    version: int = 1
    bot_id: int
    group_id: int | None = None
    persona: dict[str, Any]
    disposition: dict[str, Any] = Field(default_factory=dict)
    group_style: LegacyGroupStyleSnapshotV1 = Field(
        default_factory=lambda: LegacyGroupStyleSnapshotV1(
            ready=False,
            hints=["尚无群风格画像"],
        )
    )
    group_expression_profile: dict[str, Any] = Field(default_factory=dict)


class PersonaPromptBundleV1(BaseModel):
    system: str
    metadata: PersonaPromptMetadataV1
    sections: PersonaPromptSectionsV1


def legacy_group_style_snapshot_v1(profile: dict[str, Any]) -> LegacyGroupStyleSnapshotV1:
    aggregate = profile.get("aggregate") if isinstance(profile.get("aggregate"), dict) else {}
    reply_shape = profile.get("reply_shape") if isinstance(profile.get("reply_shape"), dict) else {}
    expression_profile = GroupExpressionProfile.model_validate(profile)
    if not group_expression_profile_ready(expression_profile):
        return LegacyGroupStyleSnapshotV1(
            ready=False,
            updated_at=str(profile.get("updated_at")) if profile.get("updated_at") else None,
            hints=["尚无群风格画像"],
        )

    message_length = aggregate.get("message_length") if isinstance(aggregate.get("message_length"), dict) else {}
    signals = LegacyGroupStyleSignalsV1(
        length_pref=str(reply_shape.get("length_pref") or "any"),
        avg_plain_len=float(message_length.get("average") or 0.0),
        p50_plain_len=int(message_length.get("p50") or 0),
        p90_plain_len=int(message_length.get("p90") or 0),
        msgs_per_hour_active=float(aggregate.get("messages_per_active_hour") or 0.0),
        local_answer_ratio=float(aggregate.get("answer_ratio") or 0.0),
        repeat_chain_rate=float(aggregate.get("repetition_rate") or 0.0),
    )
    hints: list[str] = []
    if signals.length_pref == "short":
        hints.append("群消息偏短")
    elif signals.length_pref == "long":
        hints.append("群消息偏长")
    elif signals.length_pref == "medium":
        hints.append("群消息长度适中")
    if signals.msgs_per_hour_active >= 8:
        hints.append("聊天较活跃")
    elif 0 < signals.msgs_per_hour_active < 3:
        hints.append("聊天较安静")
    if signals.repeat_chain_rate >= 0.2:
        hints.append("复读链较常见")
    return LegacyGroupStyleSnapshotV1(
        ready=True,
        updated_at=str(profile.get("updated_at")) if profile.get("updated_at") else None,
        sample=dict(aggregate),
        signals=signals,
        hints=hints,
    )


def adapt_persona_prompt_bundle_v1(bundle: PersonaPromptBundle) -> PersonaPromptBundleV1:
    profile = dict(bundle.metadata.group_expression_profile)
    return PersonaPromptBundleV1(
        system=bundle.system,
        metadata=PersonaPromptMetadataV1(
            version=bundle.metadata.version,
            bot_id=bundle.metadata.bot_id,
            group_id=bundle.metadata.group_id,
            persona=bundle.metadata.persona,
            disposition={},
            group_style=legacy_group_style_snapshot_v1(profile),
            group_expression_profile=profile,
        ),
        sections=PersonaPromptSectionsV1(
            **bundle.sections.model_dump(),
            group_style="",
            group_expression="",
        ),
    )


class PersonaAssetBundleV1(BaseModel):
    """导出给人审、WebUI 与外部站点的标准人设资产包。"""

    schema_version: Literal[1] = PERSONA_ASSET_SCHEMA_VERSION
    exported_at: int
    bot_id: int
    group_id: int | None = None
    purpose: Literal["chat"] = Field(
        default="chat",
        description=("V1 chat export only. Legacy purpose selection and online Repeater overlay export are retired."),
    )
    plain_text: str = ""
    prompt_bundle: PersonaPromptBundleV1

    @field_validator("prompt_bundle", mode="before")
    @classmethod
    def adapt_internal_prompt_bundle(cls, value: object) -> object:
        if isinstance(value, PersonaPromptBundle):
            return adapt_persona_prompt_bundle_v1(value)
        return value


def persona_asset_bundle_json_schema() -> dict[str, Any]:
    return PersonaAssetBundleV1.model_json_schema()


def persona_prompt_bundle_json_schema() -> dict[str, Any]:
    return PersonaPromptBundleV1.model_json_schema()


async def build_persona_asset_bundle_v1(
    bot_id: int,
    group_id: int | None,
    plain_text: str,
    *,
    mode: str = "normal",
) -> PersonaAssetBundleV1:
    prompt_bundle = await compile_persona_prompt_for(
        bot_id,
        group_id,
        plain_text=plain_text,
        mode=mode,
        prompt_profile=PROMPT_PROFILE_CHAT,
    )
    return PersonaAssetBundleV1(
        exported_at=int(time.time()),
        bot_id=int(bot_id),
        group_id=int(group_id) if group_id is not None else None,
        purpose="chat",
        plain_text=str(plain_text or ""),
        prompt_bundle=prompt_bundle,
    )


def serialize_persona_asset_bundle(bundle: PersonaAssetBundleV1) -> dict[str, Any]:
    return bundle.model_dump(mode="json")
