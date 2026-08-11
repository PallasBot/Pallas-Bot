from __future__ import annotations

import inspect

import pytest

from pallas.product.persona.bundle_export import (
    PersonaAssetBundleV1,
    persona_asset_bundle_json_schema,
    persona_prompt_bundle_json_schema,
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
            group_expression_profile={"reply_shape": {"length_pref": "any"}},
        ),
        sections=PersonaPromptSections(
            base="基础",
            bot_behavior="行为",
        ),
    )


def test_persona_asset_bundle_json_schema_has_version() -> None:
    schema = persona_asset_bundle_json_schema()
    assert schema["title"] == "PersonaAssetBundleV1"
    assert "prompt_bundle" in schema["properties"]
    assert "repeater_overlay" not in schema["properties"]
    assert "retired" in schema["properties"]["purpose"]["description"]


def test_serialize_persona_asset_bundle_roundtrip() -> None:
    bundle = PersonaAssetBundleV1(
        exported_at=1,
        bot_id=10,
        group_id=20,
        purpose="chat",
        plain_text="测试",
        prompt_bundle=_sample_prompt_bundle(),
    )
    payload = serialize_persona_asset_bundle(bundle)
    restored = PersonaAssetBundleV1.model_validate(payload)
    assert restored.bot_id == 10
    assert restored.purpose == "chat"
    assert restored.prompt_bundle.system.startswith("基础")


def test_v1_serialization_keeps_legacy_prompt_shape() -> None:
    bundle = PersonaAssetBundleV1(
        exported_at=1,
        bot_id=10,
        group_id=20,
        prompt_bundle=_sample_prompt_bundle(),
    )
    payload = serialize_persona_asset_bundle(bundle)
    prompt = payload["prompt_bundle"]

    assert prompt["sections"]["group_style"] == ""
    assert prompt["sections"]["group_expression"] == ""
    assert prompt["metadata"]["group_style"] == {
        "version": 1,
        "ready": False,
        "updated_at": None,
        "sample": None,
        "signals": None,
        "hints": ["尚无群风格画像"],
    }
    assert prompt["metadata"]["group_expression_profile"]["reply_shape"]["length_pref"] == "any"


def test_v1_group_style_snapshot_exposes_ready_signals_for_old_consumers() -> None:
    internal = _sample_prompt_bundle()
    internal.metadata.group_expression_profile = {
        "aggregate": {
            "sample_count": 35,
            "message_count": 30,
            "answer_count": 5,
            "messages_per_active_hour": 8.0,
            "message_length": {"average": 7.5, "p50": 6, "p90": 16},
            "answer_ratio": 0.16,
            "repetition_rate": 0.2,
        },
        "reply_shape": {"length_pref": "short"},
        "updated_at": "2026-08-11T00:00:00Z",
    }
    payload = serialize_persona_asset_bundle(PersonaAssetBundleV1(exported_at=1, bot_id=10, prompt_bundle=internal))
    legacy = payload["prompt_bundle"]["metadata"]["group_style"]

    assert legacy["ready"] is True
    assert legacy["signals"]["length_pref"] == "short"
    assert legacy["signals"]["p50_plain_len"] == 6
    assert legacy["signals"]["reply_bias_mul"] is None
    assert legacy["signals"]["civility_score"] is None
    assert "群消息偏短" in legacy["hints"]


@pytest.mark.parametrize(
    ("message_count", "answer_count", "expected"),
    [
        (0, 0, False),
        (1, 1, False),
        (29, 5, False),
        (30, 4, False),
        (30, 5, True),
    ],
)
def test_v1_group_style_ready_uses_profiler_thresholds(
    message_count: int,
    answer_count: int,
    expected: bool,
) -> None:
    internal = _sample_prompt_bundle()
    internal.metadata.group_expression_profile = {
        "aggregate": {
            "sample_count": message_count + answer_count,
            "message_count": message_count,
            "answer_count": answer_count,
        },
        "reply_shape": {"length_pref": "short"},
    }
    payload = serialize_persona_asset_bundle(PersonaAssetBundleV1(exported_at=1, bot_id=10, prompt_bundle=internal))
    legacy = payload["prompt_bundle"]["metadata"]["group_style"]
    assert legacy["ready"] is expected
    assert (legacy["signals"] is not None) is expected


def test_prompt_bundle_v1_schema_matches_serialized_legacy_shape() -> None:
    schema = persona_prompt_bundle_json_schema()
    payload = serialize_persona_asset_bundle(
        PersonaAssetBundleV1(exported_at=1, bot_id=10, prompt_bundle=_sample_prompt_bundle())
    )["prompt_bundle"]

    assert schema["title"] == "PersonaPromptBundleV1"
    sections_ref = schema["properties"]["sections"]["$ref"].rsplit("/", 1)[-1]
    metadata_ref = schema["properties"]["metadata"]["$ref"].rsplit("/", 1)[-1]
    assert {"group_style", "group_expression"} <= set(schema["$defs"][sections_ref]["properties"])
    assert {"group_style", "group_expression_profile"} <= set(schema["$defs"][metadata_ref]["properties"])
    assert set(payload) == set(schema["properties"])


@pytest.mark.asyncio
async def test_build_persona_asset_bundle_v1(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_compile(*args, **kwargs):
        return _sample_prompt_bundle()

    monkeypatch.setattr(
        "pallas.product.persona.bundle_export.compile_persona_prompt_for",
        fake_compile,
    )
    from pallas.product.persona.bundle_export import build_persona_asset_bundle_v1

    assert "purpose" not in inspect.signature(build_persona_asset_bundle_v1).parameters
    bundle = await build_persona_asset_bundle_v1(1, 2, "你好")
    assert bundle.schema_version == 1
    assert bundle.prompt_bundle.metadata.bot_id == 1
