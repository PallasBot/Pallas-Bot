"""账号稳定气质：共享核心人格之上的少量、可解释差异。"""

from __future__ import annotations

import hashlib
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AccountPersonaProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    energy: float = Field(default=0.0, ge=-1.0, le=1.0)
    warmth: float = Field(default=0.0, ge=-1.0, le=1.0)
    mischief: float = Field(default=0.0, ge=-1.0, le=1.0)
    restraint: float = Field(default=0.0, ge=-1.0, le=1.0)
    source: Literal["derived", "manual", "legacy_migrated"] = "derived"

    @model_validator(mode="after")
    def validate_manual_tendencies(self) -> Self:
        if self.source != "manual":
            return self
        nonzero_count = sum(value != 0.0 for value in (self.energy, self.warmth, self.mischief, self.restraint))
        if nonzero_count > 2:
            raise ValueError("人工牛格最多设置两个非零倾向")
        return self


def derive_account_persona_profile(bot_id: int) -> AccountPersonaProfile:
    digest = hashlib.sha256(f"pallas-account-persona:{int(bot_id)}".encode()).digest()

    def axis(index: int) -> float:
        return round((digest[index] / 255.0 - 0.5) * 0.36, 3)

    return AccountPersonaProfile(
        energy=axis(0),
        warmth=axis(1),
        mischief=axis(2),
        restraint=axis(3),
        source="derived",
    )


def migrate_legacy_seed(
    persona: dict[str, object] | None,
    bot_id: int,
) -> AccountPersonaProfile:
    from .seed import extract_stored_seed_prefs

    stored = extract_stored_seed_prefs(persona if isinstance(persona, dict) else None)
    if stored is None:
        return derive_account_persona_profile(bot_id)
    prefs, _source = stored

    migrated: dict[str, float] = {}
    if "warm" in prefs:
        migrated["warmth"] = 0.4
    if "chaotic" in prefs:
        migrated["mischief"] = 0.4
        migrated["energy"] = 0.2
    if "restrained" in prefs:
        migrated["restraint"] = 0.4
    return AccountPersonaProfile(source="legacy_migrated", **migrated)


def resolve_account_persona_profile(
    persona: dict[str, object] | None,
    bot_id: int,
) -> AccountPersonaProfile:
    if isinstance(persona, dict):
        raw_profile = persona.get("account_profile")
        if isinstance(raw_profile, dict):
            return AccountPersonaProfile.model_validate(raw_profile)
    return migrate_legacy_seed(persona, bot_id)
