"""speak_perception：提及强制 + 轻量 ambient。"""

from __future__ import annotations

import random

from pallas.product.llm.speak_perception import (
    SpeakDecision,
    clear_speak_perception_state,
    evaluate_speak_perception,
    text_mentions_aliases,
)


def test_text_mentions_aliases_login_and_default() -> None:
    aliases = ["漂亮牛", "牛牛", "帕拉斯"]
    assert text_mentions_aliases("漂亮牛出来一下", aliases)
    assert text_mentions_aliases("臭牛牛出来", aliases)
    assert text_mentions_aliases("帕拉斯在吗", aliases)
    assert not text_mentions_aliases("今天吃牛肉面", aliases)
    assert not text_mentions_aliases("随便聊聊", aliases)


def test_text_mentions_aliases_skips_short() -> None:
    assert not text_mentions_aliases("牛在吗", ["牛"], min_alias_len=2)


def test_text_mentions_aliases_strips_cq_at_noise() -> None:
    aliases = ["牛牛"]
    assert text_mentions_aliases("[CQ:at,qq=123] 牛牛出来", aliases)


def test_evaluate_to_me_always() -> None:
    clear_speak_perception_state()
    d = evaluate_speak_perception(
        plain_text="随便",
        aliases=["牛牛"],
        is_to_me=True,
        bot_id=1,
    )
    assert d.should_speak
    assert d.reason == "to_me"


def test_evaluate_mention_force() -> None:
    clear_speak_perception_state()
    d = evaluate_speak_perception(
        plain_text="漂亮牛出来",
        aliases=["漂亮牛", "牛牛"],
        is_to_me=False,
        bot_id=1,
        mention_enabled=True,
        ambient_enabled=False,
    )
    assert d.should_speak
    assert d.reason == "mention"


def test_evaluate_bystander_blocked() -> None:
    clear_speak_perception_state()
    d = evaluate_speak_perception(
        plain_text="[CQ:at,qq=999] 牛牛看看",
        aliases=["牛牛"],
        is_to_me=False,
        bot_id=1,
        mention_enabled=True,
        ambient_enabled=True,
    )
    assert not d.should_speak
    assert d.reason == "bystander"


def test_evaluate_command_like_blocked() -> None:
    clear_speak_perception_state()
    d = evaluate_speak_perception(
        plain_text="/help",
        aliases=["牛牛"],
        is_to_me=False,
        bot_id=1,
        mention_enabled=True,
        ambient_enabled=True,
    )
    assert not d.should_speak
    assert d.reason == "command"


def test_evaluate_ambient_cue_passes_rate() -> None:
    clear_speak_perception_state()
    rng = random.Random(0)
    # Random(0).random() is deterministic; force rate=1 to avoid flake
    d = evaluate_speak_perception(
        plain_text="这也太离谱了吧？",
        aliases=["牛牛"],
        is_to_me=False,
        bot_id=1,
        mention_enabled=True,
        ambient_enabled=True,
        ambient_rate=1.0,
        ambient_min_score=20,
        group_id=100,
        rng=rng,
    )
    assert d.should_speak
    assert d.reason == "ambient"
    assert isinstance(d, SpeakDecision)


def test_evaluate_ambient_miss_on_rate() -> None:
    clear_speak_perception_state()
    d = evaluate_speak_perception(
        plain_text="这也太离谱了吧？",
        aliases=["牛牛"],
        is_to_me=False,
        bot_id=1,
        ambient_enabled=True,
        ambient_rate=0.0,
        ambient_min_score=20,
        group_id=101,
        rng=random.Random(1),
    )
    assert not d.should_speak
    assert d.reason == "ambient_miss"


def test_evaluate_ambient_cooldown() -> None:
    clear_speak_perception_state()
    first = evaluate_speak_perception(
        plain_text="这也太离谱了吧？",
        aliases=["牛牛"],
        is_to_me=False,
        bot_id=1,
        ambient_enabled=True,
        ambient_rate=1.0,
        ambient_min_score=20,
        ambient_cooldown_sec=300,
        group_id=102,
        rng=random.Random(2),
        now=1000.0,
    )
    assert first.should_speak
    second = evaluate_speak_perception(
        plain_text="怎么回事啊？",
        aliases=["牛牛"],
        is_to_me=False,
        bot_id=1,
        ambient_enabled=True,
        ambient_rate=1.0,
        ambient_min_score=20,
        ambient_cooldown_sec=300,
        group_id=102,
        rng=random.Random(3),
        now=1050.0,
    )
    assert not second.should_speak
    assert second.reason == "ambient_cooldown"


def test_evaluate_ambient_disabled() -> None:
    clear_speak_perception_state()
    d = evaluate_speak_perception(
        plain_text="这也太离谱了吧？",
        aliases=["牛牛"],
        is_to_me=False,
        bot_id=1,
        mention_enabled=False,
        ambient_enabled=False,
        ambient_rate=1.0,
        group_id=103,
    )
    assert not d.should_speak
    assert d.reason in {"ambient_off", "no_trigger"}
