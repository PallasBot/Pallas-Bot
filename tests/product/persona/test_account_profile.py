from __future__ import annotations

import pytest
from pydantic import ValidationError

from pallas.product.persona.account_profile import (
    AccountPersonaProfile,
    derive_account_persona_profile,
    migrate_legacy_seed,
    resolve_account_persona_profile,
)
from pallas.product.persona.auto import derive_persona_from_bot_id
from pallas.product.persona.loader import invalidate_persona_cache, resolve_persona
from pallas.product.persona.seed import merge_persona_with_seed_patch


@pytest.mark.parametrize("field", ["energy", "warmth", "mischief", "restraint"])
def test_account_profile_rejects_axes_outside_bounds(field: str) -> None:
    with pytest.raises(ValidationError):
        AccountPersonaProfile(**{field: 1.01})
    with pytest.raises(ValidationError):
        AccountPersonaProfile(**{field: -1.01})


def test_manual_profile_accepts_at_most_two_nonzero_tendencies() -> None:
    profile = AccountPersonaProfile(source="manual", warmth=0.4, restraint=0.2)
    assert profile.warmth == 0.4
    assert profile.restraint == 0.2

    with pytest.raises(ValidationError, match="最多设置两个非零倾向"):
        AccountPersonaProfile(source="manual", energy=0.1, warmth=0.2, mischief=0.3)


def test_derived_profile_is_stable_distinct_and_bounded() -> None:
    first = derive_account_persona_profile(10001)
    assert first == derive_account_persona_profile(10001)
    assert first != derive_account_persona_profile(10002)
    assert first.source == "derived"
    assert all(abs(value) <= 0.18 for value in (first.energy, first.warmth, first.mischief, first.restraint))


def test_derived_profiles_are_centered_with_both_signs() -> None:
    values = [
        value
        for bot_id in range(10000, 10128)
        for value in (
            derive_account_persona_profile(bot_id).energy,
            derive_account_persona_profile(bot_id).warmth,
            derive_account_persona_profile(bot_id).mischief,
            derive_account_persona_profile(bot_id).restraint,
        )
    ]
    assert min(values) < 0 < max(values)
    assert abs(sum(values) / len(values)) < 0.02


def test_legacy_auto_result_carries_the_new_account_profile() -> None:
    resolved = derive_persona_from_bot_id(10001)
    assert resolved.account_profile == derive_account_persona_profile(10001)


def test_legacy_seed_migrates_expression_tendencies_but_not_length() -> None:
    warm = migrate_legacy_seed({"seed_override": {"prefs": ["warm"]}}, 7)
    chaotic = migrate_legacy_seed({"seed_override": {"prefs": ["chaotic"]}}, 7)
    restrained = migrate_legacy_seed({"seed_override": {"prefs": ["restrained"]}}, 7)
    lengths = migrate_legacy_seed({"seed_override": {"prefs": ["short", "long"]}}, 7)

    assert warm.source == "legacy_migrated"
    assert warm.warmth >= 0.35
    assert chaotic.mischief >= 0.35
    assert 0.0 < chaotic.energy <= 0.3
    assert restrained.restraint >= 0.35
    assert lengths == derive_account_persona_profile(7)


def test_empty_legacy_override_does_not_hide_stored_seed() -> None:
    profile = migrate_legacy_seed(
        {
            "seed_override": {"prefs": []},
            "seed": {"prefs": ["warm"]},
        },
        7,
    )
    assert profile.source == "legacy_migrated"
    assert profile.warmth >= 0.35


@pytest.mark.parametrize("persona", [None, {}])
def test_missing_legacy_seed_uses_small_derived_profile(persona: dict | None) -> None:
    profile = migrate_legacy_seed(persona, 7)
    assert profile.source == "derived"
    assert all(abs(value) <= 0.18 for value in (profile.energy, profile.warmth, profile.mischief, profile.restraint))


def test_explicit_account_profile_wins_and_ignores_unknown_json_fields() -> None:
    resolved = resolve_account_persona_profile(
        {
            "account_profile": {
                "source": "manual",
                "energy": 0.3,
                "warmth": 0.4,
                "future_field": "ignored",
            }
        },
        7,
    )
    assert resolved == AccountPersonaProfile(source="manual", energy=0.3, warmth=0.4)


def test_profile_patch_preserves_aliases_and_peer_aliases() -> None:
    merged = merge_persona_with_seed_patch(
        {
            "self_aliases": ["猪猪"],
            "peer_aliases": ["隔壁牛"],
            "custom_future_field": {"enabled": True},
        },
        {"account_profile": {"source": "manual", "warmth": 0.5}},
        bot_id=7,
    )

    assert merged["self_aliases"] == ["猪猪"]
    assert merged["peer_aliases"] == ["隔壁牛"]
    assert merged["custom_future_field"] == {"enabled": True}
    assert merged["account_profile"] == AccountPersonaProfile(source="manual", warmth=0.5).model_dump()


@pytest.mark.asyncio
async def test_loader_carries_account_profile_without_applying_legacy_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyBotRepo:
        async def get(self, key, ignore_cache=False):  # noqa: ARG002
            return type(
                "BotCfg",
                (),
                {
                    "group_style_enabled": True,
                    "persona": {"seed_override": {"prefs": ["warm", "short"]}},
                },
            )()

    monkeypatch.setattr("pallas.product.persona.loader.make_bot_config_repository", lambda: DummyBotRepo())
    invalidate_persona_cache()

    resolved = await resolve_persona(10001)

    assert resolved.account_profile.source == "legacy_migrated"
    assert resolved.account_profile.warmth >= 0.35


@pytest.mark.asyncio
async def test_loader_uses_derived_profile_for_empty_bot_config(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyBotRepo:
        async def get(self, key, ignore_cache=False):  # noqa: ARG002
            return type("BotCfg", (), {"group_style_enabled": True, "persona": {}})()

    monkeypatch.setattr("pallas.product.persona.loader.make_bot_config_repository", lambda: DummyBotRepo())
    invalidate_persona_cache()

    resolved = await resolve_persona(10001)

    assert resolved.account_profile.source == "derived"
    assert all(
        abs(value) <= 0.18
        for value in (
            resolved.account_profile.energy,
            resolved.account_profile.warmth,
            resolved.account_profile.mischief,
            resolved.account_profile.restraint,
        )
    )


@pytest.mark.asyncio
async def test_message_persona_reuses_one_group_profile_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.persona.loader import resolve_persona_for_message

    calls = 0

    class DummyBotRepo:
        async def get(self, key, ignore_cache=False):  # noqa: ARG002
            return type("BotCfg", (), {"group_style_enabled": True, "persona": {}})()

    class DummyGroupRepo:
        async def get(self, key, ignore_cache=False):  # noqa: ARG002
            nonlocal calls
            calls += 1
            return type(
                "GroupCfg",
                (),
                {
                    "style_profile": {
                        "sample": {
                            "message_count": 30,
                            "answer_count": 5,
                            "affect_triggers": [{"phrase": "牛牛税", "warmth_delta": 0.1}],
                        },
                        "derived": {"length_pref": "short"},
                    }
                },
            )()

    monkeypatch.setattr("pallas.product.persona.loader.make_bot_config_repository", lambda: DummyBotRepo())
    monkeypatch.setattr("pallas.product.persona.loader.make_group_config_repository", lambda: DummyGroupRepo())
    invalidate_persona_cache()

    resolved = await resolve_persona_for_message(10001, 20002, "牛牛税")

    assert calls == 1
    assert resolved.group_expression_profile.reply_shape.length_pref == "short"
    assert resolved.affect_triggers[0]["phrase"] == "牛牛税"
    assert resolved.warmth > 0
