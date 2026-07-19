from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from operator import itemgetter

import pytest

from pallas.product.persona.auto import derive_persona_from_bot_id
from pallas.product.persona.scorer import (
    answer_popularity_multiplier,
    chaos_message_multiplier,
    freshness_multiplier,
    low_info_multiplier,
    message_weight_multiplier,
    scaled_answer_threshold,
    scaled_speak_threshold,
)


def test_derive_persona_differs_by_bot_id() -> None:
    a = derive_persona_from_bot_id(10001)
    b = derive_persona_from_bot_id(10002)
    assert a.reply_bias != b.reply_bias or a.tone != b.tone or a.length_pref != b.length_pref


def test_reply_bias_lowers_threshold() -> None:
    from pallas.product.persona.model import ResolvedPersona

    chatty = ResolvedPersona(reply_bias=1.4)
    quiet = ResolvedPersona(reply_bias=0.7)
    base = 3
    assert scaled_answer_threshold(base, chatty, in_hosted_activity=False) < base
    assert scaled_answer_threshold(base, quiet, in_hosted_activity=False) > base


def test_message_weight_prefers_short_for_terse_preset() -> None:
    from pallas.product.persona.model import ResolvedPersona

    persona = ResolvedPersona(length_pref="short", tone="terse")
    assert message_weight_multiplier("好", persona) > message_weight_multiplier(
        "这是一句明显偏长的接话测试文本", persona
    )


def test_low_info_multiplier() -> None:
    assert low_info_multiplier("。") < low_info_multiplier("好的")


def test_scaled_speak_threshold() -> None:
    from pallas.product.persona.model import ResolvedPersona

    assert scaled_speak_threshold(5, ResolvedPersona(speak_bias=2.0)) == pytest.approx(2.5)


def test_chaos_message_multiplier_prefers_short_text() -> None:
    from pallas.product.persona.model import ResolvedPersona

    chaotic = ResolvedPersona(chaos_bias=0.2)
    calm = ResolvedPersona(chaos_bias=0.0)
    assert chaos_message_multiplier("好", chaotic) > chaos_message_multiplier("好", calm)
    assert chaos_message_multiplier(
        "这是一段明显偏长的接话测试文本，用于验证高 chaos 群会压低长句",
        chaotic,
    ) < chaos_message_multiplier("好", chaotic)


def test_answer_popularity_multiplier_prefers_hot_answers_when_chaotic() -> None:
    from pallas.product.persona.model import ResolvedPersona

    chaotic = ResolvedPersona(chaos_bias=0.2)
    calm = ResolvedPersona(chaos_bias=0.0)
    assert answer_popularity_multiplier(10, chaotic) > answer_popularity_multiplier(1, chaotic)
    assert answer_popularity_multiplier(1, calm) >= answer_popularity_multiplier(10, calm)


def test_message_weight_multiplier_uses_chaos_bias() -> None:
    from pallas.product.persona.model import ResolvedPersona

    chaotic = ResolvedPersona(length_pref="any", tone="neutral", chaos_bias=0.2)
    calm = ResolvedPersona(length_pref="any", tone="neutral", chaos_bias=0.0)
    assert message_weight_multiplier("草", chaotic) > message_weight_multiplier("草", calm)


def test_freshness_multiplier_tolerates_repeat_when_chaotic() -> None:
    from pallas.product.persona.model import ResolvedPersona

    chaotic = ResolvedPersona(chaos_bias=0.2)
    calm = ResolvedPersona(chaos_bias=0.0)
    assert freshness_multiplier("同一句", ["同一句"], persona=chaotic) > freshness_multiplier(
        "同一句", ["同一句"], persona=calm
    )


@pytest.mark.asyncio
async def test_resolve_persona_merges_group_style_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.persona.loader import invalidate_persona_cache, resolve_persona
    from pallas.product.persona.model import ResolvedPersona

    class DummyGroupRepo:
        async def get(self, key, ignore_cache=False):  # noqa: ARG002
            return type(
                "GroupCfg",
                (),
                {
                    "style_profile": {
                        "derived": {
                            "reply_bias_mul": 1.1,
                            "speak_bias_mul": 0.95,
                            "length_pref": "long",
                            "chaos_bias": 0.2,
                            "warmth_bias": 0.1,
                            "assertiveness_bias": 0.15,
                        }
                    }
                },
            )()

    class DummyBotRepo:
        async def get(self, key, ignore_cache=False):  # noqa: ARG002
            return type("BotCfg", (), {"group_style_enabled": True})()

    monkeypatch.setattr(
        "pallas.product.persona.loader.derive_persona_from_bot_id",
        lambda _bid, archetype_enabled=True: ResolvedPersona(
            reply_bias=1.0,
            speak_bias=1.0,
            length_pref="short",
            chaos_bias=0.05,
            warmth=0.0,
            assertiveness=0.0,
        ),
    )
    monkeypatch.setattr("pallas.product.persona.loader.make_group_config_repository", lambda: DummyGroupRepo())
    monkeypatch.setattr("pallas.product.persona.loader.make_bot_config_repository", lambda: DummyBotRepo())

    invalidate_persona_cache()
    resolved = await resolve_persona(10001, 20002)

    assert resolved.reply_bias == pytest.approx(1.1)
    assert resolved.speak_bias == pytest.approx(0.95)
    assert resolved.length_pref == "long"
    assert resolved.chaos_bias == pytest.approx(0.2)
    assert resolved.warmth == pytest.approx(0.1)
    assert resolved.assertiveness == pytest.approx(0.15)


@pytest.mark.asyncio
async def test_resolve_persona_skips_group_style_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.persona.loader import invalidate_persona_cache, resolve_persona
    from pallas.product.persona.model import ResolvedPersona

    class DummyGroupRepo:
        async def get(self, key, ignore_cache=False):  # noqa: ARG002
            return type("GroupCfg", (), {"style_profile": {"derived": {"reply_bias_mul": 1.2}}})()

    class DummyBotRepo:
        async def get(self, key, ignore_cache=False):  # noqa: ARG002
            return type("BotCfg", (), {"group_style_enabled": False})()

    monkeypatch.setattr(
        "pallas.product.persona.loader.derive_persona_from_bot_id",
        lambda _bid, archetype_enabled=True: ResolvedPersona(
            reply_bias=1.0,
            speak_bias=1.0,
            length_pref="short",
            chaos_bias=0.05,
            warmth=0.0,
            assertiveness=0.0,
        ),
    )
    monkeypatch.setattr("pallas.product.persona.loader.make_group_config_repository", lambda: DummyGroupRepo())
    monkeypatch.setattr("pallas.product.persona.loader.make_bot_config_repository", lambda: DummyBotRepo())

    invalidate_persona_cache()
    resolved = await resolve_persona(10001, 20002)

    assert resolved.reply_bias == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_speaker_uses_group_aware_persona(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater.speaker import Speaker

    @dataclass
    class _Msg:
        raw_message: str
        keywords: str
        user_id: int
        time: int

    reply_dict = {123: {1001: [{"time": 1, "reply": "旧回复", "reply_keywords": "旧"}]}}

    async def fake_resolve_persona(bot_id: int, group_id: int | None = None):
        assert bot_id == 1001
        assert group_id == 123
        from pallas.product.persona.model import ResolvedPersona

        return ResolvedPersona(speak_bias=2.0)

    monkeypatch.setattr("packages.repeater.speaker.resolve_persona", fake_resolve_persona)
    monkeypatch.setattr("packages.repeater.speaker.blocks_proactive_speak", lambda _gid: False)
    monkeypatch.setattr("pallas.core.platform.shard.registry.config.is_sharding_active", lambda: False)
    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.platform_utils.pick_connected_bot_id", lambda ids, log_tag=None: 1001
    )  # noqa: ARG005

    async def fake_find_ban_keywords(**_kwargs):
        return set()

    monkeypatch.setattr("packages.repeater.ban_manager.BanManager.find_ban_keywords", fake_find_ban_keywords)

    async def fake_taken_name(self):
        return None

    monkeypatch.setattr("pallas.core.foundation.config.BotConfig.taken_name", fake_taken_name)
    monkeypatch.setattr("packages.repeater.speaker.random.choice", itemgetter(0))
    monkeypatch.setattr("packages.repeater.speaker.random.random", lambda: 1.0)
    monkeypatch.setattr("packages.repeater.speaker.time.time", lambda: 10_000.0)
    monkeypatch.setattr(
        "packages.repeater.speaker.Speaker._pick_speak_message",
        lambda persona, pool, recently: pool[-1],
    )

    message_dict = {
        123: [_Msg(f"m{i}", f"k{i % 2}", i + 1, i * 10) for i in range(12)],
    }
    monkeypatch.setattr("packages.repeater.speaker.MessageStore._message_dict", message_dict)

    result = await Speaker.speak(
        reply_dict, __import__("asyncio").Lock(), defaultdict(lambda: deque(maxlen=16)), __import__("asyncio").Lock()
    )

    assert result is not None


def test_speak_keyword_group_weight_prefers_hot_topic_when_chaotic() -> None:
    from types import SimpleNamespace

    from pallas.product.persona.model import ResolvedPersona
    from pallas.product.persona.scorer import speak_keyword_group_weight

    hot = [SimpleNamespace(plain_text="草", raw_message="草") for _ in range(8)]
    cold = [SimpleNamespace(plain_text="冷门句", raw_message="冷门句")]
    chaotic = ResolvedPersona(chaos_bias=0.2, length_pref="short")
    calm = ResolvedPersona(chaos_bias=0.0, length_pref="any")

    assert speak_keyword_group_weight(hot, chaotic, recent_speaks=[]) > speak_keyword_group_weight(
        cold, chaotic, recent_speaks=[]
    )
    assert speak_keyword_group_weight(hot, chaotic, recent_speaks=[]) > speak_keyword_group_weight(
        hot, calm, recent_speaks=[]
    )


def test_pick_speak_message_prefers_popular_keywords() -> None:
    from collections import Counter, deque
    from types import SimpleNamespace

    from packages.repeater.speaker import Speaker
    from pallas.product.persona.model import ResolvedPersona

    hot_msgs = [SimpleNamespace(keywords="hot", plain_text="草", raw_message="草", user_id=1) for _ in range(8)]
    cold_msgs = [
        SimpleNamespace(keywords="cold", plain_text="偏长的冷门话题句", raw_message="偏长的冷门话题句", user_id=2)
    ]
    pool = hot_msgs + cold_msgs
    persona = ResolvedPersona(chaos_bias=0.2, length_pref="short", tone="terse")
    counts: Counter[str] = Counter()
    for _ in range(300):
        picked = Speaker._pick_speak_message(persona, pool, deque())
        counts[picked.keywords] += 1
    assert counts["hot"] > counts["cold"]
