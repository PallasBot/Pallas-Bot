"""账号牛格轻量种子。"""

from __future__ import annotations

from pallas.product.persona.auto import derive_persona_from_bot_id
from pallas.product.persona.seed import (
    apply_seed_prefs,
    derive_auto_seed_prefs,
    merge_persona_with_seed_patch,
    normalize_seed_prefs,
    resolve_effective_seed_prefs,
)


def test_normalize_seed_prefs_caps_and_filters() -> None:
    assert normalize_seed_prefs(["short", "chaotic", "nope", "warm"]) == ["chaotic", "warm"]
    assert normalize_seed_prefs(["warm", "restrained", "chaotic"]) == ["warm", "restrained"]


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


def test_apply_seed_prefs_changes_persona_axes() -> None:
    base = derive_persona_from_bot_id(42, archetype_enabled=False)
    chaotic = apply_seed_prefs(base, ["chaotic"])
    warm = apply_seed_prefs(base, ["warm"])
    restrained = apply_seed_prefs(base, ["restrained"])

    assert chaotic.chaos_bias > base.chaos_bias
    assert chaotic.assertiveness > base.assertiveness
    assert warm.warmth > base.warmth
    assert restrained.warmth < base.warmth
    assert restrained.chaos_bias <= base.chaos_bias


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
    assert merged["seed_override"]["prefs"] == ["chaotic"]
    assert merged["seed_override"]["source"] == "manual"


def test_merge_persona_with_seed_patch_updates_disposition_without_losing_seed() -> None:
    existing = {
        "seed": {"prefs": ["warm"]},
        "seed_override": {"prefs": ["short"]},
        "cross_group": {"tone": "calm"},
    }

    merged = merge_persona_with_seed_patch(
        existing,
        {
            "disposition": {
                "approach": "先接住再判断",
                "do": ["说重点", "留接话口"],
            },
        },
        bot_id=7,
    )

    assert merged["seed_override"] == {"prefs": ["short"]}
    assert merged["cross_group"] == {"tone": "calm"}
    assert merged["disposition"] == {
        "version": 1,
        "approach": "先接住再判断",
        "initiative": "",
        "conflict": "",
        "do": ["说重点", "留接话口"],
        "dont": [],
    }

    cleared = merge_persona_with_seed_patch(merged, {"disposition": {}}, bot_id=7)

    assert "disposition" not in cleared
