"""Persona 资产导出（OPT-LLM-024）：跨站点可复用的 JSON bundle + schema。"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from pallas.product.persona.compile_persona_prompt import PersonaPromptBundle, compile_persona_prompt_for

PERSONA_ASSET_SCHEMA_VERSION = 1


class RepeaterOverlayExport(BaseModel):
    purpose: str
    system_prompt: str
    temperature: float | None = None
    token_count: int | None = None
    affect_block: str = ""
    variation_hint: str = ""
    dynamic_expression_hint: str = ""
    llm_rewrite_metadata: dict[str, Any] = Field(default_factory=dict)


class PersonaAssetBundleV1(BaseModel):
    """导出给人审、WebUI 与外部站点的标准人设资产包。"""

    schema_version: Literal[1] = PERSONA_ASSET_SCHEMA_VERSION
    exported_at: int
    bot_id: int
    group_id: int | None = None
    purpose: str
    plain_text: str = ""
    prompt_bundle: PersonaPromptBundle
    repeater_overlay: RepeaterOverlayExport | None = None


def persona_asset_bundle_json_schema() -> dict[str, Any]:
    return PersonaAssetBundleV1.model_json_schema()


def persona_prompt_bundle_json_schema() -> dict[str, Any]:
    return PersonaPromptBundle.model_json_schema()


async def build_persona_asset_bundle_v1(
    bot_id: int,
    group_id: int | None,
    plain_text: str,
    *,
    purpose: str = "chat",
    mode: str = "normal",
    include_repeater_overlay: bool = False,
) -> PersonaAssetBundleV1:
    from pallas.product.llm.repeater_persona_context import build_repeater_llm_persona_context
    from pallas.product.persona.compile_persona_prompt import resolve_prompt_profile_for_purpose

    prompt_bundle = await compile_persona_prompt_for(
        bot_id,
        group_id,
        plain_text=plain_text,
        mode=mode,
        prompt_profile=resolve_prompt_profile_for_purpose(purpose),
    )
    overlay: RepeaterOverlayExport | None = None
    if include_repeater_overlay and group_id is not None:
        repeater_bundle = await build_repeater_llm_persona_context(
            bot_id,
            int(group_id),
            plain_text,
            purpose=purpose,
            mode=mode,
        )
        if repeater_bundle is not None:
            overlay = RepeaterOverlayExport(
                purpose=purpose,
                system_prompt=repeater_bundle.system_prompt,
                temperature=repeater_bundle.temperature,
                token_count=repeater_bundle.token_count,
                affect_block=repeater_bundle.affect_block,
                variation_hint=repeater_bundle.variation_hint,
                dynamic_expression_hint=repeater_bundle.dynamic_expression_hint,
                llm_rewrite_metadata=dict(repeater_bundle.llm_rewrite_metadata),
            )
    return PersonaAssetBundleV1(
        exported_at=int(time.time()),
        bot_id=int(bot_id),
        group_id=int(group_id) if group_id is not None else None,
        purpose=str(purpose or "chat"),
        plain_text=str(plain_text or ""),
        prompt_bundle=prompt_bundle,
        repeater_overlay=overlay,
    )


def serialize_persona_asset_bundle(bundle: PersonaAssetBundleV1) -> dict[str, Any]:
    return bundle.model_dump(mode="json")
