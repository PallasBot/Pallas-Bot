"""轻量记忆候选观察队列。"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path  # noqa: TC003
from typing import Literal

from pydantic import BaseModel, Field

ObservationStatus = Literal["pending", "accepted", "rejected"]
_MAX_QUEUE_SIZE = 500


class ObservationRecord(BaseModel):
    observation_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    bot_id: int
    group_id: int
    user_id: int
    text: str
    source: str
    created_at: int = Field(default_factory=lambda: int(time.time()))
    status: ObservationStatus = "pending"


def _queue_path() -> Path:
    from pallas.product.llm.memory.ops import _data_dir

    return _data_dir() / "observation_queue.json"


def _read_records() -> list[ObservationRecord]:
    path = _queue_path()
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    return [ObservationRecord.model_validate(item) for item in items if isinstance(item, dict)]


def _write_records(records: list[ObservationRecord]) -> None:
    path = _queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"items": [item.model_dump(mode="json") for item in records]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def observe_message(
    *,
    bot_id: int,
    group_id: int,
    user_id: int,
    text: str,
    source: str = "message",
) -> ObservationRecord:
    record = ObservationRecord(
        bot_id=bot_id,
        group_id=group_id,
        user_id=user_id,
        text=text.strip(),
        source=source.strip() or "message",
    )
    records = _read_records()
    records.append(record)
    pending = [item for item in records if item.status == "pending"]
    if len(pending) > _MAX_QUEUE_SIZE:
        remove = len(pending) - _MAX_QUEUE_SIZE
        records = [item for item in records if item.status != "pending" or (remove := remove - 1) < 0]
    _write_records(records)
    return record


def list_observations(
    *,
    bot_id: int | None = None,
    group_id: int | None = None,
    status: ObservationStatus | None = "pending",
    limit: int = 100,
) -> list[ObservationRecord]:
    records = _read_records()
    out = [
        item
        for item in records
        if (bot_id is None or item.bot_id == bot_id)
        and (group_id is None or item.group_id == group_id)
        and (status is None or item.status == status)
    ]
    return out[: max(1, min(limit, _MAX_QUEUE_SIZE))]


def dequeue_observations(*, limit: int = 50) -> list[ObservationRecord]:
    records = _read_records()
    selected: list[ObservationRecord] = []
    remaining: list[ObservationRecord] = []
    capacity = max(1, min(limit, _MAX_QUEUE_SIZE))
    for item in records:
        if item.status == "pending" and len(selected) < capacity:
            selected.append(item)
        else:
            remaining.append(item)
    _write_records(remaining)
    return selected


def observation_queue_size() -> int:
    return sum(item.status == "pending" for item in _read_records())


def clear_observations_for_tests() -> None:
    path = _queue_path()
    if path.is_file():
        path.unlink()
