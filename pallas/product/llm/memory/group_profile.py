"""群体话题、梗与互动规范的轻量快照。"""

from __future__ import annotations

import json
import time
from pathlib import Path  # noqa: TC003

from pydantic import BaseModel, Field


class GroupProfileSnapshot(BaseModel):
    group_id: int
    topics: list[str] = Field(default_factory=list)
    memes: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    active_hours: list[int] = Field(default_factory=list)
    norms: list[str] = Field(default_factory=list)
    updated_at: int = Field(default_factory=lambda: int(time.time()))


def _store_path() -> Path:
    from pallas.product.llm.memory.ops import _data_dir

    return _data_dir() / "group_profiles.json"


def _read_profiles() -> list[GroupProfileSnapshot]:
    path = _store_path()
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = raw.get("items") if isinstance(raw, dict) else raw
    return [GroupProfileSnapshot.model_validate(item) for item in items or [] if isinstance(item, dict)]


def _write_profiles(profiles: list[GroupProfileSnapshot]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"items": [item.model_dump(mode="json") for item in profiles]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def get_group_profile(group_id: int) -> GroupProfileSnapshot:
    for profile in _read_profiles():
        if profile.group_id == group_id:
            return profile
    return GroupProfileSnapshot(group_id=group_id)


def upsert_group_profile_hints(
    group_id: int,
    *,
    topics: list[str] | None = None,
    memes: list[str] | None = None,
    roles: list[str] | None = None,
    active_hours: list[int] | None = None,
    norms: list[str] | None = None,
) -> GroupProfileSnapshot:
    current = get_group_profile(group_id)
    updates = {}
    for name, value in (
        ("topics", topics),
        ("memes", memes),
        ("roles", roles),
        ("active_hours", active_hours),
        ("norms", norms),
    ):
        if value is not None:
            updates[name] = list(value)
    updated = current.model_copy(update={**updates, "updated_at": int(time.time())})
    profiles = [item for item in _read_profiles() if item.group_id != group_id]
    profiles.append(updated)
    _write_profiles(profiles)
    return updated


def compile_group_profile_prompt_lines(profile: GroupProfileSnapshot) -> list[str]:
    lines: list[str] = []
    for label, values in (
        ("常聊话题", profile.topics),
        ("群内梗", profile.memes),
        ("群体角色", profile.roles),
        ("群内规范", profile.norms),
    ):
        if values:
            lines.append(f"- {label}：{'、'.join(str(value) for value in values[:12])}")
    if profile.active_hours:
        lines.append(f"- 活跃时段：{', '.join(str(hour) for hour in profile.active_hours[:24])}点")
    return lines
