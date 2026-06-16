from __future__ import annotations

import time

import pytest

from src.features.persona.cross_group_profiler import (
    MAX_GROUP_WEIGHT,
    build_bot_cross_group_persona,
    group_style_weight,
)


def _style_profile(
    *,
    answer_count: int,
    message_count: int = 32,
    reply_bias_mul: float = 1.1,
    speak_bias_mul: float = 1.0,
    length_pref: str = "short",
    chaos_bias: float = 0.1,
    updated_at: int | None = None,
) -> dict:
    now = int(updated_at or time.time())
    return {
        "version": 1,
        "updated_at": now,
        "sample": {
            "window_hours": 168,
            "message_count": message_count,
            "answer_count": answer_count,
            "distinct_answer_keywords": max(1, answer_count // 2),
        },
        "derived": {
            "reply_bias_mul": reply_bias_mul,
            "speak_bias_mul": speak_bias_mul,
            "length_pref": length_pref,
            "chaos_bias": chaos_bias,
        },
    }


def test_group_style_weight_caps_large_group() -> None:
    huge = _style_profile(answer_count=1_000_000, message_count=32)
    small = _style_profile(answer_count=20, message_count=10)
    now = int(time.time())
    assert group_style_weight(huge, now_ts=now) == pytest.approx(MAX_GROUP_WEIGHT)
    assert group_style_weight(small, now_ts=now) < group_style_weight(huge, now_ts=now)


def test_group_style_weight_decays_with_age() -> None:
    now = int(time.time())
    fresh = _style_profile(answer_count=500, updated_at=now)
    stale = _style_profile(answer_count=500, updated_at=now - 8 * 24 * 3600)
    assert group_style_weight(fresh, now_ts=now) > group_style_weight(stale, now_ts=now)


def test_build_bot_cross_group_persona_requires_multiple_groups() -> None:
    profile = build_bot_cross_group_persona(
        bot_id=1001,
        group_profiles=[(1, _style_profile(answer_count=500))],
    )
    assert "derived" not in profile
    assert profile["sample"]["group_count"] == 1


def test_build_bot_cross_group_persona_weighted_average() -> None:
    profiles = [
        (1, _style_profile(answer_count=500, reply_bias_mul=1.15, chaos_bias=0.2, length_pref="long")),
        (2, _style_profile(answer_count=200, reply_bias_mul=1.0, chaos_bias=0.0, length_pref="short")),
    ]
    profile = build_bot_cross_group_persona(bot_id=1001, group_profiles=profiles)
    derived = profile["derived"]
    assert derived["reply_bias_mul"] > 1.0
    assert derived["chaos_bias"] > 0.0
    assert derived["length_pref"] in {"short", "medium", "long"}
    assert profile["sample"]["group_count"] == 2
    assert profile["source"] == "cross_group"


@pytest.mark.asyncio
async def test_resolve_persona_applies_cross_group_before_group(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.features.persona.loader import invalidate_persona_cache, resolve_persona
    from src.features.persona.model import ResolvedPersona

    class DummyGroupRepo:
        async def get(self, key, ignore_cache=False):  # noqa: ARG002
            return type(
                "GroupCfg",
                (),
                {
                    "style_profile": {
                        "derived": {
                            "reply_bias_mul": 1.1,
                            "speak_bias_mul": 1.0,
                            "length_pref": "long",
                            "chaos_bias": 0.2,
                        }
                    }
                },
            )()

    class DummyBotRepo:
        async def get(self, key, ignore_cache=False):  # noqa: ARG002
            return type(
                "BotCfg",
                (),
                {
                    "group_style_enabled": True,
                    "persona": {
                        "source": "cross_group",
                        "derived": {
                            "reply_bias_mul": 1.2,
                            "speak_bias_mul": 1.0,
                            "length_pref": "short",
                            "chaos_bias": 0.05,
                        },
                    },
                },
            )()

    monkeypatch.setattr(
        "src.features.persona.loader.derive_persona_from_bot_id",
        lambda _bid: ResolvedPersona(reply_bias=1.0, speak_bias=1.0, length_pref="any", chaos_bias=0.0),
    )
    monkeypatch.setattr("src.features.persona.loader.make_group_config_repository", lambda: DummyGroupRepo())
    monkeypatch.setattr("src.features.persona.loader.make_bot_config_repository", lambda: DummyBotRepo())

    invalidate_persona_cache()
    resolved = await resolve_persona(10001, 20002)

    assert resolved.reply_bias == pytest.approx(1.2 * 1.1)
    assert resolved.length_pref == "long"
    assert resolved.chaos_bias == pytest.approx(0.2)
