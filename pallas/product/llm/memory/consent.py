"""跨群使用用户稳定偏好的授权记录。"""

from __future__ import annotations

import json
import time
from pathlib import Path  # noqa: TC003

from pydantic import BaseModel, Field


class ConsentRecord(BaseModel):
    user_id: int
    platform: str
    granted: bool = False
    updated_at: int = Field(default_factory=lambda: int(time.time()))
    scopes: list[str] = Field(default_factory=list)


def _store_path() -> Path:
    from pallas.product.llm.memory.ops import _data_dir

    return _data_dir() / "person_consent.json"


def _read_records() -> list[ConsentRecord]:
    path = _store_path()
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = raw.get("items") if isinstance(raw, dict) else raw
    return [ConsentRecord.model_validate(item) for item in items or [] if isinstance(item, dict)]


def _write_records(records: list[ConsentRecord]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"items": [item.model_dump(mode="json") for item in records]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def get_consent(user_id: int, *, platform: str = "qq") -> ConsentRecord:
    for record in _read_records():
        if record.user_id == user_id and record.platform == platform:
            return record
    return ConsentRecord(user_id=user_id, platform=platform)


def set_consent(
    user_id: int,
    *,
    platform: str = "qq",
    granted: bool,
    scopes: list[str] | None = None,
) -> ConsentRecord:
    record = ConsentRecord(
        user_id=user_id,
        platform=platform,
        granted=granted,
        scopes=[str(scope).strip() for scope in scopes or [] if str(scope).strip()],
        updated_at=int(time.time()),
    )
    records = _read_records()
    records = [item for item in records if not (item.user_id == user_id and item.platform == platform)]
    records.append(record)
    _write_records(records)
    return record


def can_use_global_person_facts(user_id: int, *, platform: str = "qq") -> bool:
    record = get_consent(user_id, platform=platform)
    return record.granted and (
        not record.scopes or "stable_preferences" in record.scopes or "person_facts" in record.scopes
    )
