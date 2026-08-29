"""按用户维护的稳定事实，默认限定在当前群。"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path  # noqa: TC003
from typing import Literal

from pydantic import BaseModel, Field

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


def _store_path() -> Path:
    from pallas.product.llm.memory.ops import _data_dir

    return _data_dir() / "person_facts.json"


def _read_facts() -> list[PersonFact]:
    path = _store_path()
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = raw.get("items") if isinstance(raw, dict) else raw
    return [PersonFact.model_validate(item) for item in items or [] if isinstance(item, dict)]


def _write_facts(facts: list[PersonFact]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"items": [fact.model_dump(mode="json") for fact in facts]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
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
    facts = _read_facts()
    facts.append(fact)
    _write_facts(facts)
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
    facts = _read_facts()
    same_source = [
        fact
        for fact in facts
        if fact.bot_id == int(bot_id)
        and fact.group_id == int(group_id)
        and fact.user_id == int(user_id)
        and fact.source == source
        and fact.status == "active"
    ]
    if any(fact.content.casefold() == normalized.casefold() for fact in same_source):
        return None
    now = int(time.time())
    forgotten_ids = {fact.fact_id for fact in same_source}
    next_facts = [
        fact.model_copy(update={"status": "forgotten", "updated_at": now}) if fact.fact_id in forgotten_ids else fact
        for fact in facts
    ]
    fact = PersonFact(
        bot_id=int(bot_id),
        group_id=int(group_id),
        user_id=int(user_id),
        content=normalized,
        source=source.strip() or "conversation",
        confidence=max(0.0, min(1.0, confidence)),
        scope="group",
        created_at=now,
        updated_at=now,
    )
    next_facts.append(fact)
    _write_facts(next_facts)
    return fact


def forget_person_facts_by_source(*, bot_id: int, group_id: int, user_id: int, sources: list[str]) -> int:
    """把指定 source 集合的 active 事实置 forgotten，返回失活条数。

    供 top-K 类确定性管线在产出缩水时清理多余的键控事实。
    """
    wanted = {str(source) for source in sources if str(source)}
    if not wanted:
        return 0
    facts = _read_facts()
    now = int(time.time())
    hit = 0
    next_facts: list[PersonFact] = []
    for fact in facts:
        if (
            fact.bot_id == int(bot_id)
            and fact.group_id == int(group_id)
            and fact.user_id == int(user_id)
            and fact.source in wanted
            and fact.status == "active"
        ):
            next_facts.append(fact.model_copy(update={"status": "forgotten", "updated_at": now}))
            hit += 1
        else:
            next_facts.append(fact)
    if hit:
        _write_facts(next_facts)
    return hit


def forget_group_person_facts_by_source(*, bot_id: int, group_id: int, sources: list[str]) -> int:
    """把群内指定 source 集合的 active 事实全部置 forgotten。"""
    wanted = {str(source) for source in sources if str(source)}
    if not wanted:
        return 0
    facts = _read_facts()
    now = int(time.time())
    hit = 0
    next_facts: list[PersonFact] = []
    for fact in facts:
        if (
            fact.bot_id == int(bot_id)
            and fact.group_id == int(group_id)
            and fact.source in wanted
            and fact.status == "active"
        ):
            next_facts.append(fact.model_copy(update={"status": "forgotten", "updated_at": now}))
            hit += 1
        else:
            next_facts.append(fact)
    if hit:
        _write_facts(next_facts)
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
    facts = _read_facts()
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
        _write_facts(facts)
        return updated
    return None


def update_person_fact_status(fact_id: str, status: PersonFactStatus) -> PersonFact | None:
    facts = _read_facts()
    for index, fact in enumerate(facts):
        if fact.fact_id == fact_id:
            updated = fact.model_copy(update={"status": status, "updated_at": int(time.time())})
            facts[index] = updated
            _write_facts(facts)
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
