"""受控的场景正反例存储与本轮选择。"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from pallas.core.foundation.fs_lock import atomic_write_text, interprocess_file_lock
from pallas.core.foundation.paths import plugin_data_dir
from pallas.product.persona.occasion import normalize_occasion_tag
from pallas.product.persona.prompt_guard import sanitize_prompt_literal

SCENE_DIALOGUE_EXAMPLE_SCHEMA_VERSION = 1
MAX_SCENE_DIALOGUE_EXAMPLES_PER_BOT = 48
MAX_SELECT_SCENE_DIALOGUE_EXAMPLES = 3


class SceneDialogueExample(BaseModel):
    schema_version: int = Field(default=SCENE_DIALOGUE_EXAMPLE_SCHEMA_VERSION, ge=1, le=1)
    example_id: str = Field(min_length=1, max_length=80)
    bot_id: int = Field(ge=1)
    scene: str = Field(min_length=1, max_length=32)
    user_cue: str = Field(min_length=1, max_length=120)
    positive: str = Field(min_length=1, max_length=280)
    negative: str = Field(min_length=1, max_length=280)
    enabled: bool = True
    order: int = Field(default=0, ge=0, le=9999)
    created_at: int = Field(default_factory=lambda: int(time.time()))
    updated_at: int = Field(default_factory=lambda: int(time.time()))

    @field_validator("scene", mode="before")
    @classmethod
    def normalize_scene(cls, value: object) -> str:
        scene = normalize_occasion_tag(str(value or "").strip())
        if not scene:
            raise ValueError("scene required")
        return scene

    @field_validator("user_cue", "positive", "negative", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip())


def _path() -> Path:
    root = (
        Path(os.environ["PALLAS_DATA_DIR"])
        if os.environ.get("PALLAS_DATA_DIR")
        else plugin_data_dir("pb_webui", create=True)
    )
    path = root / "persona" / "scene_dialogue_examples.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load() -> list[SceneDialogueExample]:
    path = _path()
    if not path.exists():
        return []
    rows: list[SceneDialogueExample] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(SceneDialogueExample.model_validate_json(line))
        except (TypeError, ValueError):
            continue
    return rows


def _save(rows: list[SceneDialogueExample]) -> None:
    atomic_write_text(
        _path(),
        "".join(json.dumps(row.model_dump(mode="json"), ensure_ascii=False) + "\n" for row in rows),
    )


def list_scene_dialogue_examples(bot_id: int | None = None) -> list[SceneDialogueExample]:
    rows = [row for row in _load() if bot_id is None or row.bot_id == int(bot_id)]
    return sorted(rows, key=lambda row: (row.order, row.created_at, row.example_id))


def create_scene_dialogue_example(
    *,
    bot_id: int,
    scene: str,
    user_cue: str,
    positive: str,
    negative: str,
    enabled: bool = True,
    order: int = 0,
) -> SceneDialogueExample:
    path = _path()
    with interprocess_file_lock(path.with_suffix(".lock")):
        rows = _load()
        if len([row for row in rows if row.bot_id == int(bot_id)]) >= MAX_SCENE_DIALOGUE_EXAMPLES_PER_BOT:
            raise ValueError(f"最多保留 {MAX_SCENE_DIALOGUE_EXAMPLES_PER_BOT} 条场景对话示例")
        item = SceneDialogueExample(
            example_id=f"scene-example-{uuid.uuid4().hex[:12]}",
            bot_id=int(bot_id),
            scene=scene,
            user_cue=user_cue,
            positive=positive,
            negative=negative,
            enabled=enabled,
            order=order,
        )
        rows.append(item)
        _save(rows)
        return item


def update_scene_dialogue_example(example_id: str, **changes: object) -> SceneDialogueExample | None:
    path = _path()
    with interprocess_file_lock(path.with_suffix(".lock")):
        rows = _load()
        for index, row in enumerate(rows):
            if row.example_id != example_id:
                continue
            allowed = {"scene", "user_cue", "positive", "negative", "enabled", "order"}
            update = {key: value for key, value in changes.items() if key in allowed and value is not None}
            rows[index] = row.model_copy(update={**update, "updated_at": int(time.time())})
            rows[index] = SceneDialogueExample.model_validate(rows[index].model_dump())
            _save(rows)
            return rows[index]
    return None


def delete_scene_dialogue_example(example_id: str) -> bool:
    path = _path()
    with interprocess_file_lock(path.with_suffix(".lock")):
        rows = _load()
        kept = [row for row in rows if row.example_id != example_id]
        if len(kept) == len(rows):
            return False
        _save(kept)
        return True


def _keywords(text: str) -> set[str]:
    plain = str(text or "").lower()
    cjk = "".join(char for char in plain if "\u4e00" <= char <= "\u9fff")
    tokens = {cjk[index : index + 2] for index in range(max(0, len(cjk) - 1))}
    tokens.update(re.findall(r"[a-z0-9_]{2,}", plain))
    return tokens


def select_scene_dialogue_examples_for_turn(
    bot_id: int,
    *,
    scene: str,
    user_text: str,
    limit: int = MAX_SELECT_SCENE_DIALOGUE_EXAMPLES,
) -> list[SceneDialogueExample]:
    scene_key = normalize_occasion_tag(str(scene or "").strip())
    if not scene_key or int(limit) <= 0:
        return []
    query = _keywords(user_text)
    scored: list[tuple[int, SceneDialogueExample]] = []
    for item in list_scene_dialogue_examples(int(bot_id)):
        if not item.enabled or item.scene != scene_key:
            continue
        overlap = len(query & _keywords(item.user_cue))
        scored.append((overlap, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1].order, -pair[1].updated_at, pair[1].example_id))
    return [item for _, item in scored[: min(MAX_SELECT_SCENE_DIALOGUE_EXAMPLES, int(limit))]]


def build_scene_dialogue_examples_hint(
    bot_id: int,
    *,
    scene: str,
    user_text: str,
    limit: int = MAX_SELECT_SCENE_DIALOGUE_EXAMPLES,
) -> tuple[str, list[SceneDialogueExample]]:
    rows = select_scene_dialogue_examples_for_turn(bot_id, scene=scene, user_text=user_text, limit=limit)
    if not rows:
        return "", []
    lines = ["【本轮场景正反例】理解每组对比表达的方向，不要复述或套用其中原句。"]
    for item in rows:
        cue = sanitize_prompt_literal(item.user_cue, max_len=120)
        positive = sanitize_prompt_literal(item.positive, max_len=280)
        negative = sanitize_prompt_literal(item.negative, max_len=280)
        lines.extend((f"场景 {item.scene}，用户线索：{cue}", f"建议：{positive}", f"避免：{negative}"))
    return "\n".join(lines), rows
