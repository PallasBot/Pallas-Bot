"""Bot 自称与群昵称（如「牛牛」）注入 persona prompt。"""

from __future__ import annotations

import re
from typing import Any

from pallas.core.foundation.db import make_bot_config_repository
from pallas.product.persona.prompt_guard import sanitize_prompt_literal, wrap_stats_block

DEFAULT_SELF_ALIASES: tuple[str, ...] = ("牛牛", "帕拉斯", "Pallas")

_SELF_ALIAS_TEACH_RE = re.compile(
    r"^(?:记住[：:]?\s*)?"
    r"(?P<alias>.+?)"
    r"(?:就是我|是我)$"
)
_SELF_ALIAS_POINTS_YOU_RE = re.compile(
    r"^(?:记住[：:]?\s*)?"
    r"(?P<alias>.+?)"
    r"(?:指的是你|就是指你|指的是bot|指的是机器人)$",
    re.IGNORECASE,
)
_SELF_ALIAS_EQUALS_RE = re.compile(r"^(?P<left>[\u4e00-\u9fffA-Za-z·]{1,12})\s*[=＝]\s*(?:我|你|bot|Bot|机器人)$")
_SELF_ALIAS_MEANS_RE = re.compile(
    r"^(?P<alias>[\u4e00-\u9fffA-Za-z·]{1,12})\s*(?:指的是|就是指|就是)\s*(?:你|我|bot|Bot|机器人)$"
)


def extract_self_aliases(bot_persona: dict[str, Any] | None) -> list[str]:
    aliases: list[str] = list(DEFAULT_SELF_ALIASES)
    seen = {item.casefold() for item in aliases}
    if not isinstance(bot_persona, dict):
        return aliases
    raw = bot_persona.get("self_aliases")
    if raw is None:
        raw = bot_persona.get("alias_names")
    if not isinstance(raw, list):
        return aliases
    for item in raw:
        text = sanitize_prompt_literal(str(item or "").strip(), max_len=16)
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        aliases.append(text)
    return aliases


def compile_self_identity_prompt(bot_persona: dict[str, Any] | None = None) -> str:
    alias_text = "、".join(extract_self_aliases(bot_persona)[:6])
    primary_alias = alias_text.split("、")[0] if alias_text else "牛牛"
    body = "\n".join([
        "【自称与群称呼】",
        f"- 群友常叫你「{primary_alias}」等——这些称呼指你本人。",
        "- 有人 @ 你或在句中喊上述名字时，默认是在跟你说话；用第一人称接话，不要当成第三者在聊。",
        "- 禁止把「牛牛」当外人夸奖（错误：「牛牛真棒」）；应理解成在说你，用「谢谢」「还行吧」等第一人称回应。",
        "- 自称优先用「我」；必要时可用群昵称指代自己，但不要每句都加动物口癖或句尾 ASCII 颜文字。",
    ])
    return wrap_stats_block("self_identity", body)


def compile_repeater_self_identity_prompt(bot_persona: dict[str, Any] | None = None) -> str:
    aliases = extract_self_aliases(bot_persona)
    primary_alias = aliases[0] if aliases else "牛牛"
    body = "\n".join([
        "【群称呼】",
        f"- 群友喊「{primary_alias}」等时是在跟你说话；用第一人称接，别把称呼当第三者在聊。",
        "- 日常接话不必自我介绍帕拉斯或罗德岛，像群友顺口回一句即可。",
    ])
    return wrap_stats_block("self_identity", body)


def parse_self_alias_teach(plain_text: str) -> list[str]:
    body = str(plain_text or "").strip()
    if not body or len(body) > 48:
        return []
    for pattern in (_SELF_ALIAS_TEACH_RE, _SELF_ALIAS_POINTS_YOU_RE, _SELF_ALIAS_EQUALS_RE, _SELF_ALIAS_MEANS_RE):
        matched = pattern.match(body)
        if not matched:
            continue
        alias = str(matched.groupdict().get("alias") or matched.groupdict().get("left") or "").strip()
        safe = sanitize_prompt_literal(alias, max_len=16)
        if safe and safe.casefold() not in {"我", "你", "bot"}:
            return [safe]
    return []


async def save_self_alias_from_teach(bot_id: int, plain_text: str) -> bool:
    aliases = parse_self_alias_teach(plain_text)
    if not aliases:
        return False
    repo = make_bot_config_repository()
    doc = await repo.get(int(bot_id))
    persona: dict[str, Any] = {}
    if doc is not None and isinstance(getattr(doc, "persona", None), dict):
        persona = dict(doc.persona)
    merged = extract_self_aliases(persona)
    seen = {item.casefold() for item in merged}
    changed = False
    for alias in aliases:
        if alias.casefold() in seen:
            continue
        seen.add(alias.casefold())
        merged.append(alias)
        changed = True
    if not changed:
        return True
    persona["self_aliases"] = [item for item in merged if item not in DEFAULT_SELF_ALIASES][:8]
    await repo.upsert_field(int(bot_id), "persona", persona)
    return True
