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
_SELF_ALIAS_IS_YOU_RE = re.compile(
    r"^(?:记住[：:]?\s*)?"
    r"(?P<alias>[\u4e00-\u9fffA-Za-z·]{1,12})"
    r"(?:就是你|是你)$"
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
# 观察型称呼：不打断对话，静默写入 self_aliases
_SELF_ALIAS_OBSERVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^大家(?:都)?叫你(?P<alias>[\u4e00-\u9fffA-Za-z·]{1,12})$"),
    re.compile(r"^群友(?:都)?叫你(?P<alias>[\u4e00-\u9fffA-Za-z·]{1,12})$"),
    re.compile(r"^你的(?:外号|昵称|群名片)(?:是|叫)(?P<alias>[\u4e00-\u9fffA-Za-z·]{1,12})$"),
    re.compile(r"^(?P<alias>[\u4e00-\u9fffA-Za-z·]{1,12})是你的(?:外号|昵称|群名片)$"),
    re.compile(r"^你(?:就)?是(?P<alias>[\u4e00-\u9fffA-Za-z·]{2,12})$"),
)
_ALIAS_BLOCKLIST = frozenset({"我", "你", "bot", "谁", "什么", "啥", "哪位", "哪个", "机器人"})


def extract_self_aliases(
    bot_persona: dict[str, Any] | None,
    *,
    login_nickname: str | None = None,
) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        text = sanitize_prompt_literal(str(raw or "").strip(), max_len=16)
        if not text or text.casefold() in seen:
            return
        if text.casefold() in {item.casefold() for item in _ALIAS_BLOCKLIST}:
            return
        seen.add(text.casefold())
        aliases.append(text)

    login = _safe_alias(str(login_nickname or ""))
    if login:
        add(login)
    for item in DEFAULT_SELF_ALIASES:
        add(item)
    if not isinstance(bot_persona, dict):
        return aliases
    raw = bot_persona.get("self_aliases")
    if raw is None:
        raw = bot_persona.get("alias_names")
    if not isinstance(raw, list):
        return aliases
    for item in raw:
        add(str(item or ""))
    return aliases


def compile_self_identity_prompt(
    bot_persona: dict[str, Any] | None = None,
    *,
    login_nickname: str | None = None,
) -> str:
    aliases = extract_self_aliases(bot_persona, login_nickname=login_nickname)
    alias_text = "、".join(aliases[:6])
    primary_alias = aliases[0] if aliases else "牛牛"
    login = _safe_alias(str(login_nickname or ""))
    if login and login != "牛牛":
        call_line = f"- 群友常叫你「{primary_alias}」等（含「牛牛」）——这些称呼指你本人。"
    else:
        call_line = f"- 群友常叫你「{primary_alias}」等——这些称呼指你本人。"
    body = "\n".join([
        "【自称与群称呼】",
        call_line,
        f"- 常见称呼：{alias_text}。",
        "- 有人 @ 你或在句中喊上述名字时，默认是在跟你说话；用第一人称接话，不要当成第三者在聊。",
        "- 禁止把「牛牛」当外人夸奖（错误：「牛牛真棒」）；应理解成在说你，用「谢谢」「还行吧」等第一人称回应。",
        "- 自称优先用「我」；必要时可用群昵称指代自己，但不要每句都加动物口癖或句尾 ASCII 颜文字。",
    ])
    return wrap_stats_block("self_identity", body)


def compile_repeater_self_identity_prompt(
    bot_persona: dict[str, Any] | None = None,
    *,
    login_nickname: str | None = None,
) -> str:
    aliases = extract_self_aliases(bot_persona, login_nickname=login_nickname)
    primary_alias = aliases[0] if aliases else "牛牛"
    if primary_alias == "牛牛":
        call_line = "- 群友喊「牛牛」等时是在跟你说话；用第一人称接，别把称呼当第三者在聊。"
    else:
        call_line = f"- 群友喊「{primary_alias}」或「牛牛」等时是在跟你说话；用第一人称接，别把称呼当第三者在聊。"
    body = "\n".join([
        "【群称呼】",
        call_line,
        "- 日常接话不必自我介绍帕拉斯或罗德岛，像群友顺口回一句即可。",
    ])
    return wrap_stats_block("self_identity", body)


def resolve_cached_login_nickname(bot_id: int) -> str:
    """同步尽力取昵称：presence → 协议 accounts display_name。"""
    sid = str(int(bot_id))
    try:
        from pallas.core.platform.shard.presence import read_presence_bots

        rec = read_presence_bots().get(sid)
        if isinstance(rec, dict):
            nick = str(rec.get("nickname") or "").strip()
            if nick:
                return nick
    except Exception:
        pass
    try:
        from pallas.console.webui.protocol_accounts import protocol_account_display_names

        return str(protocol_account_display_names().get(sid) or "").strip()
    except Exception:
        return ""


async def resolve_login_nickname(bot_id: int) -> str:
    """优先 OneBot get_login_info，失败则回退缓存。"""
    sid = str(int(bot_id))
    try:
        from nonebot import get_bots

        bot = get_bots().get(sid)
        if bot is not None:
            raw = await bot.call_api("get_login_info")  # type: ignore[union-attr]
            if isinstance(raw, dict):
                nick = str(raw.get("nickname") or "").strip()
                if nick:
                    return nick
    except Exception:
        pass
    return resolve_cached_login_nickname(bot_id)


def _safe_alias(raw: str) -> str | None:
    safe = sanitize_prompt_literal(str(raw or "").strip(), max_len=16)
    if not safe or safe.casefold() in {item.casefold() for item in _ALIAS_BLOCKLIST}:
        return None
    return safe


def parse_self_alias_teach(plain_text: str) -> list[str]:
    body = str(plain_text or "").strip()
    if not body or len(body) > 48:
        return []
    for pattern in (
        _SELF_ALIAS_POINTS_YOU_RE,
        _SELF_ALIAS_MEANS_RE,
        _SELF_ALIAS_EQUALS_RE,
        _SELF_ALIAS_IS_YOU_RE,
        _SELF_ALIAS_TEACH_RE,
    ):
        matched = pattern.match(body)
        if not matched:
            continue
        alias = str(matched.groupdict().get("alias") or matched.groupdict().get("left") or "").strip()
        safe = _safe_alias(alias)
        if safe:
            return [safe]
    return []


def parse_self_alias_observe(plain_text: str) -> list[str]:
    """弱模式：从闲聊句沉淀称呼，不打断主对话。"""
    body = str(plain_text or "").strip()
    if not body or len(body) > 32:
        return []
    if parse_self_alias_teach(body):
        return []
    for pattern in _SELF_ALIAS_OBSERVE_PATTERNS:
        matched = pattern.match(body)
        if not matched:
            continue
        safe = _safe_alias(str(matched.group("alias") or ""))
        if safe:
            return [safe]
    return []


async def merge_self_aliases(bot_id: int, aliases: list[str]) -> bool:
    cleaned = [item for item in (_safe_alias(alias) for alias in aliases) if item]
    if not cleaned:
        return False
    repo = make_bot_config_repository()
    doc = await repo.get(int(bot_id))
    persona: dict[str, Any] = {}
    if doc is not None and isinstance(getattr(doc, "persona", None), dict):
        persona = dict(doc.persona)
    merged = extract_self_aliases(persona)
    seen = {item.casefold() for item in merged}
    changed = False
    for alias in cleaned:
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


async def save_self_alias_from_teach(bot_id: int, plain_text: str) -> bool:
    aliases = parse_self_alias_teach(plain_text)
    if not aliases:
        return False
    return await merge_self_aliases(bot_id, aliases)


async def maybe_persist_self_alias_from_utterance(bot_id: int, plain_text: str) -> bool:
    aliases = parse_self_alias_observe(plain_text)
    if not aliases:
        return False
    return await merge_self_aliases(bot_id, aliases)
