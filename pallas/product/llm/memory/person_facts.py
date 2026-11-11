"""按用户维护的稳定事实，默认限定在当前群。"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path  # noqa: TC003
from typing import Literal

from nonebot import logger
from pydantic import BaseModel, Field

from pallas.core.foundation.fs_lock import atomic_write_text, interprocess_file_lock
from pallas.core.foundation.logging import log_rate_limited

PersonFactScope = Literal["group", "global"]
PersonFactStatus = Literal["active", "frozen", "forgotten"]


class PersonFact(BaseModel):
    fact_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    bot_id: int
    group_id: int
    user_id: int
    content: str
    source: str
    confidence: float = 0.5
    scope: PersonFactScope = "group"
    status: PersonFactStatus = "active"
    created_at: int = Field(default_factory=lambda: int(time.time()))
    updated_at: int = Field(default_factory=lambda: int(time.time()))
    version: int = 1


class PersonFactsStoreError(ValueError):
    """Stored person facts are not safe to mutate."""


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PersonFactsStoreError("person facts store contains duplicate keys")
        result[key] = value
    return result


def _store_path() -> Path:
    from pallas.product.llm.memory.ops import _data_dir

    return _data_dir() / "person_facts.json"


def _read_fact_items_unlocked(path: Path) -> list[object] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if os.path.lexists(path):
            raise PersonFactsStoreError("person facts store target is missing") from None
        return None
    except Exception:
        raise PersonFactsStoreError("person facts store could not be read") from None
    try:
        raw = json.loads(text, object_pairs_hook=_unique_json_object)
    except Exception:
        raise PersonFactsStoreError("person facts store contains invalid JSON") from None
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        return raw["items"]
    raise PersonFactsStoreError("person facts store has an invalid structure")


def _read_facts_unlocked(path: Path) -> list[PersonFact]:
    items = _read_fact_items_unlocked(path)
    if items is None:
        return []
    facts: list[PersonFact] = []
    for item in items:
        try:
            facts.append(PersonFact.model_validate(item))
        except Exception:
            raise PersonFactsStoreError("person facts store contains invalid records") from None
    return facts


def _warn_tolerant_read() -> None:
    log_rate_limited(
        logger,
        "warning",
        "llm.person_facts.read",
        "人物事实存储异常，读取时已忽略无法解析的数据",
    )


def _read_facts() -> list[PersonFact]:
    # Writers replace atomically, so readers can parse one complete snapshot without queuing behind them.
    try:
        items = _read_fact_items_unlocked(_store_path())
    except (PersonFactsStoreError, OSError):
        _warn_tolerant_read()
        return []
    if items is None:
        return []
    facts: list[PersonFact] = []
    invalid_records = False
    for item in items:
        try:
            facts.append(PersonFact.model_validate(item))
        except Exception:
            invalid_records = True
    if invalid_records:
        _warn_tolerant_read()
    return facts


def _write_facts_unlocked(facts: list[PersonFact], path: Path) -> None:
    atomic_write_text(
        path,
        json.dumps({"items": [fact.model_dump(mode="json") for fact in facts]}, ensure_ascii=False, indent=2) + "\n",
    )


def save_person_fact(
    *,
    bot_id: int,
    group_id: int,
    user_id: int,
    content: str,
    source: str = "conversation",
    confidence: float = 0.5,
    scope: PersonFactScope = "group",
) -> PersonFact:
    safe_scope: PersonFactScope = scope if scope in ("group", "global") else "group"
    if safe_scope == "global":
        from pallas.product.llm.memory.consent import can_use_global_person_facts

        if not can_use_global_person_facts(user_id, platform="qq"):
            safe_scope = "group"
    now = int(time.time())
    fact = PersonFact(
        bot_id=bot_id,
        group_id=0 if safe_scope == "global" else group_id,
        user_id=user_id,
        content=content.strip(),
        source=source.strip() or "conversation",
        confidence=max(0.0, min(1.0, confidence)),
        scope=safe_scope,
        created_at=now,
        updated_at=now,
    )
    path = _store_path()
    # ponytail: a single lock covers the shared JSON file; partition only if writer contention warrants it.
    with interprocess_file_lock(path.with_suffix(".lock")):
        facts = _read_facts_unlocked(path)
        facts.append(fact)
        _write_facts_unlocked(facts, path)
    return fact


def replace_person_fact_by_source(
    *,
    bot_id: int,
    group_id: int,
    user_id: int,
    source: str,
    content: str,
    confidence: float = 0.5,
) -> PersonFact | None:
    """按 source 键控替换同一 (bot, group, user) 的画像事实。

    同 source 且 casefold 同文的 active 事实已存在时 no-op；否则把该来源的
    旧 active 事实置 forgotten 再追加新条，供确定性管线（如表情包习惯）反复
    刷新同一条画像而不堆积。content 为空时不做任何改动。
    """
    normalized = content.strip()
    if not normalized:
        return None
    created = replace_person_facts_by_source_batch(
        bot_id=bot_id,
        group_id=group_id,
        replacements=[(user_id, source, normalized, confidence)],
    )
    return created[0] if created else None


def replace_person_facts_by_source_batch(
    *,
    bot_id: int,
    group_id: int,
    replacements: list[tuple[int, str, str, float]],
    forget_sources_by_user: dict[int, list[str]] | None = None,
) -> list[PersonFact]:
    """在单次读写事务中替换多名用户的键控事实并清理多余来源。"""
    return replace_person_facts_by_scope_batch(
        replacements=[
            (bot_id, group_id, user_id, source, content, confidence)
            for user_id, source, content, confidence in replacements
        ],
        forget_sources_by_scope={
            (bot_id, group_id, user_id): sources for user_id, sources in (forget_sources_by_user or {}).items()
        },
    )


def replace_person_facts_by_scope_batch(
    *,
    replacements: list[tuple[int, int, int, str, str, float]],
    forget_sources_by_scope: dict[tuple[int, int, int | None], list[str]] | None = None,
) -> list[PersonFact]:
    """Across scopes, apply keyed replacements and cleanup with one locked read/write."""
    if not replacements and not forget_sources_by_scope:
        return []
    path = _store_path()
    with interprocess_file_lock(path.with_suffix(".lock")):
        facts = _read_facts_unlocked(path)
        active_by_source: dict[tuple[int, int, int, str], list[int]] = {}
        active_by_group_source: dict[tuple[int, int, str], list[int]] = {}
        for index, fact in enumerate(facts):
            if fact.status == "active":
                active_by_source.setdefault((fact.bot_id, fact.group_id, fact.user_id, fact.source), []).append(index)
                active_by_group_source.setdefault((fact.bot_id, fact.group_id, fact.source), []).append(index)

        now = int(time.time())
        created: list[PersonFact] = []
        changed = False
        for bot_id, group_id, user_id, source, content, confidence in replacements:
            normalized = content.strip()
            if not normalized:
                continue
            bot_id, group_id, user_id = int(bot_id), int(group_id), int(user_id)
            key = (bot_id, group_id, user_id, source)
            indexes = active_by_source.get(key, [])
            if any(facts[index].content.casefold() == normalized.casefold() for index in indexes):
                continue
            for index in indexes:
                facts[index] = facts[index].model_copy(update={"status": "forgotten", "updated_at": now})
            fact = PersonFact(
                bot_id=bot_id,
                group_id=group_id,
                user_id=user_id,
                content=normalized,
                source=source.strip() or "conversation",
                confidence=max(0.0, min(1.0, confidence)),
                scope="group",
                created_at=now,
                updated_at=now,
            )
            facts.append(fact)
            active_by_source[key] = [len(facts) - 1]
            active_by_group_source.setdefault((bot_id, group_id, source), []).append(len(facts) - 1)
            created.append(fact)
            changed = True

        for (bot_id, group_id, user_id), sources in (forget_sources_by_scope or {}).items():
            for source in {str(item) for item in sources if str(item)}:
                indexes = (
                    active_by_group_source.get((int(bot_id), int(group_id), source), [])
                    if user_id is None
                    else active_by_source.get((int(bot_id), int(group_id), int(user_id), source), [])
                )
                for index in indexes:
                    fact = facts[index]
                    if fact.status == "active":
                        facts[index] = fact.model_copy(update={"status": "forgotten", "updated_at": now})
                        changed = True

        if changed:
            _write_facts_unlocked(facts, path)
        return created


def forget_person_facts_by_source(*, bot_id: int, group_id: int, user_id: int, sources: list[str]) -> int:
    """把指定 source 集合的 active 事实置 forgotten，返回失活条数。

    供 top-K 类确定性管线在产出缩水时清理多余的键控事实。
    """
    wanted = {str(source) for source in sources if str(source)}
    if not wanted:
        return 0
    path = _store_path()
    with interprocess_file_lock(path.with_suffix(".lock")):
        facts = _read_facts_unlocked(path)
        now = int(time.time())
        hit = 0
        for index, fact in enumerate(facts):
            if (
                fact.bot_id == int(bot_id)
                and fact.group_id == int(group_id)
                and fact.user_id == int(user_id)
                and fact.source in wanted
                and fact.status == "active"
            ):
                facts[index] = fact.model_copy(update={"status": "forgotten", "updated_at": now})
                hit += 1
        if hit:
            _write_facts_unlocked(facts, path)
    return hit


def forget_group_person_facts_by_source(*, bot_id: int, group_id: int, sources: list[str]) -> int:
    """把群内指定 source 集合的 active 事实全部置 forgotten。"""
    wanted = {str(source) for source in sources if str(source)}
    if not wanted:
        return 0
    path = _store_path()
    with interprocess_file_lock(path.with_suffix(".lock")):
        facts = _read_facts_unlocked(path)
        now = int(time.time())
        hit = 0
        for index, fact in enumerate(facts):
            if (
                fact.bot_id == int(bot_id)
                and fact.group_id == int(group_id)
                and fact.source in wanted
                and fact.status == "active"
            ):
                facts[index] = fact.model_copy(update={"status": "forgotten", "updated_at": now})
                hit += 1
        if hit:
            _write_facts_unlocked(facts, path)
    return hit


def list_person_facts(
    *,
    bot_id: int | None = None,
    group_id: int | None = None,
    user_id: int | None = None,
    status: PersonFactStatus | None = "active",
    limit: int = 100,
) -> list[PersonFact]:
    facts = _read_facts()
    return [
        fact
        for fact in facts
        if (bot_id is None or fact.bot_id == bot_id)
        and (group_id is None or fact.group_id == group_id)
        and (user_id is None or fact.user_id == user_id)
        and (status is None or fact.status == status)
    ][: max(1, min(limit, 200))]


def correct_person_fact(fact_id: str, content: str, *, confidence: float | None = None) -> PersonFact | None:
    path = _store_path()
    with interprocess_file_lock(path.with_suffix(".lock")):
        facts = _read_facts_unlocked(path)
        for index, fact in enumerate(facts):
            if fact.fact_id != fact_id:
                continue
            updated = fact.model_copy(
                update={
                    "content": content.strip(),
                    "confidence": fact.confidence if confidence is None else max(0.0, min(1.0, confidence)),
                    "updated_at": int(time.time()),
                    "version": fact.version + 1,
                    "status": "active",
                }
            )
            facts[index] = updated
            _write_facts_unlocked(facts, path)
            return updated
    return None


def update_person_fact_status(fact_id: str, status: PersonFactStatus) -> PersonFact | None:
    path = _store_path()
    with interprocess_file_lock(path.with_suffix(".lock")):
        facts = _read_facts_unlocked(path)
        for index, fact in enumerate(facts):
            if fact.fact_id == fact_id:
                updated = fact.model_copy(update={"status": status, "updated_at": int(time.time())})
                facts[index] = updated
                _write_facts_unlocked(facts, path)
                return updated
    return None


def freeze_person_fact(fact_id: str) -> PersonFact | None:
    return update_person_fact_status(fact_id, "frozen")


def forget_person_fact(fact_id: str) -> PersonFact | None:
    return update_person_fact_status(fact_id, "forgotten")


def retrieve_person_facts_for_prompt(
    *,
    bot_id: int,
    group_id: int,
    user_id: int,
    limit: int = 8,
) -> list[str]:
    facts = list_person_facts(bot_id=bot_id, user_id=user_id, limit=200)
    allow_global = False
    from pallas.product.llm.memory.consent import can_use_global_person_facts

    allow_global = can_use_global_person_facts(user_id, platform="qq")
    lines = [
        fact.content
        for fact in facts
        if (fact.scope == "group" and fact.group_id == group_id) or (fact.scope == "global" and allow_global)
    ]
    return lines[: max(1, min(limit, 20))]
