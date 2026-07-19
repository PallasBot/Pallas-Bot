"""账号牛格轻量种子。"""

from __future__ import annotations

from pallas.product.persona.auto import derive_persona_from_bot_id
from pallas.product.persona.scorer import message_weight_multiplier
from pallas.product.persona.seed import (
    apply_seed_prefs,
    derive_auto_seed_prefs,
    merge_persona_with_seed_patch,
    normalize_seed_prefs,
    resolve_effective_seed_prefs,
)


def test_normalize_seed_prefs_caps_and_filters() -> None:
    assert normalize_seed_prefs(["short", "chaotic", "nope", "warm"]) == ["short", "chaotic"]


def test_derive_auto_seed_prefs_differs_by_archetype() -> None:
    prefs_a = derive_auto_seed_prefs(100)
    prefs_b = derive_auto_seed_prefs(101)
    prefs_c = derive_auto_seed_prefs(102)
    assert prefs_a != prefs_b or prefs_b != prefs_c or prefs_a != prefs_c


def test_manual_override_beats_auto_seed() -> None:
    prefs, source = resolve_effective_seed_prefs(
        {
            "seed": {"prefs": ["short", "chaotic"]},
            "seed_override": {"prefs": ["restrained"]},
        },
        bot_id=1,
    )
    assert source == "manual"
    assert prefs == ["restrained"]


def test_apply_seed_prefs_changes_message_weights() -> None:
    base = derive_persona_from_bot_id(42, archetype_enabled=False)
    short_persona = apply_seed_prefs(base, ["short"])
    long_persona = apply_seed_prefs(base, ["long"])
    short_text = "草"
    long_text = "今天这件事其实挺复杂的，我觉得还是再想想比较好吧。"
    assert message_weight_multiplier(short_text, short_persona) > message_weight_multiplier(short_text, long_persona)
    assert message_weight_multiplier(long_text, long_persona) > message_weight_multiplier(long_text, short_persona)


def test_merge_persona_with_seed_patch_preserves_cross_group() -> None:
    existing = {
        "version": 1,
        "source": "cross_group",
        "derived": {"chaos_bias": 0.1},
        "seed": {"prefs": ["warm"]},
    }
    merged = merge_persona_with_seed_patch(
        existing,
        {"seed_override": {"prefs": ["chaotic", "short"]}},
        bot_id=7,
    )
    assert merged["source"] == "cross_group"
    assert merged["derived"]["chaos_bias"] == 0.1
    assert merged["seed_override"]["prefs"] == ["chaotic", "short"]
    assert merged["seed_override"]["source"] == "manual"
