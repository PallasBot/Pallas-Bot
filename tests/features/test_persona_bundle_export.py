from __future__ import annotations

import pytest

from pallas.product.persona.bundle_export import (
    PersonaAssetBundleV1,
    persona_asset_bundle_json_schema,
    serialize_persona_asset_bundle,
)
from pallas.product.persona.compile_persona_prompt import (
    PersonaPromptBundle,
    PersonaPromptMetadata,
    PersonaPromptSections,
)


def _sample_prompt_bundle() -> PersonaPromptBundle:
    return PersonaPromptBundle(
        system="基础\n【接话塑形】\n- 像群友接话",
        metadata=PersonaPromptMetadata(
            bot_id=1,
            group_id=2,
            persona={"tone": "neutral"},
            group_style={"ready": False},
        ),
        sections=PersonaPromptSections(
            base="基础",
            bot_behavior="行为",
            group_style="群风",
        ),
    )


def test_persona_asset_bundle_json_schema_has_version() -> None:
    schema = persona_asset_bundle_json_schema()
    assert schema["title"] == "PersonaAssetBundleV1"
    assert "prompt_bundle" in schema["properties"]


def test_serialize_persona_asset_bundle_roundtrip() -> None:
    bundle = PersonaAssetBundleV1(
        exported_at=1,
        bot_id=10,
        group_id=20,
        purpose="polish_lite",
        plain_text="测试",
        prompt_bundle=_sample_prompt_bundle(),
    )
    payload = serialize_persona_asset_bundle(bundle)
    restored = PersonaAssetBundleV1.model_validate(payload)
    assert restored.bot_id == 10
    assert restored.prompt_bundle.system.startswith("基础")


@pytest.mark.asyncio
async def test_build_persona_asset_bundle_v1(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_compile(*args, **kwargs):
        return _sample_prompt_bundle()

    monkeypatch.setattr(
        "pallas.product.persona.bundle_export.compile_persona_prompt_for",
        fake_compile,
    )
    from pallas.product.persona.bundle_export import build_persona_asset_bundle_v1

    bundle = await build_persona_asset_bundle_v1(1, 2, "你好", purpose="chat")
    assert bundle.schema_version == 1
    assert bundle.prompt_bundle.metadata.bot_id == 1
