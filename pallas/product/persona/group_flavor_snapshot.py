"""Stable group flavor snapshot for decision and generation layers."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GroupFlavorSnapshot(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    group_id: int
    summary: str = ""
    expression_habits: list[str] = Field(default_factory=list)
    ending_habits: list[str] = Field(default_factory=list)
    tone_tags: list[str] = Field(default_factory=list)


def build_group_flavor_snapshot(group_id: int, profile: dict | None) -> GroupFlavorSnapshot:
    data = dict(profile or {})
    habits = data.get("expression_habits") if isinstance(data.get("expression_habits"), list) else []
    endings = data.get("ending_habits") if isinstance(data.get("ending_habits"), list) else []
    tone_tags = data.get("tone_tags") if isinstance(data.get("tone_tags"), list) else []
    summary = str(data.get("summary") or data.get("style_summary") or "").strip()
    return GroupFlavorSnapshot(
        group_id=int(group_id),
        summary=summary,
        expression_habits=[str(item).strip() for item in habits if str(item).strip()],
        ending_habits=[str(item).strip() for item in endings if str(item).strip()],
        tone_tags=[str(item).strip() for item in tone_tags if str(item).strip()],
    )
